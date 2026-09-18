"""Campus event MVP. Python 3.10+, standard library only."""
import argparse
import csv
import io
import json
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from agents import runtime
from agents import playground
from agents.contracts import validate_plan

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('EVENT_DB', str(ROOT / 'events.sqlite3')))
LOCK = threading.RLock()
FIELDS = {'name': '活动名称', 'objective': '活动目标', 'type': '活动类型', 'level': '活动级别', 'format': '活动形式', 'date': '活动时间', 'location': '活动地点', 'audience': '目标参与者', 'capacity': '预计人数', 'budget': '预算', 'organizer': '主办方', 'owner': '负责人'}
STATES = ['DRAFT', 'WAITING_PLAN_CONFIRMATION', 'PLAN_CONFIRMED', 'WAITING_PUBLICITY_CONFIRMATION', 'REGISTRATION_OPEN', 'LIVE', 'FEEDBACK', 'WAITING_REVIEW_CONFIRMATION', 'WAITING_RECAP_CONFIRMATION', 'COMPLETED']


class Problem(Exception):
    pass


def now():
    return datetime.now().isoformat(timespec='seconds')


def init_db():
    with sqlite3.connect(DB) as c:
        c.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS agent_runs (id TEXT PRIMARY KEY, event_id TEXT, data TEXT NOT NULL)')
        c.execute('INSERT OR IGNORE INTO config VALUES (?, ?)', ('admin_token', secrets.token_urlsafe(32)))


def admin_token():
    with sqlite3.connect(DB) as c:
        return c.execute("SELECT value FROM config WHERE key='admin_token'").fetchone()[0]


def load(eid):
    with sqlite3.connect(DB) as c:
        row = c.execute('SELECT data FROM events WHERE id=?', (eid,)).fetchone()
    if not row:
        raise Problem('活动不存在')
    return json.loads(row[0])


def save(e):
    e['updated_at'] = now()
    e['version'] = e.get('version', 0) + 1
    with sqlite3.connect(DB) as c:
        c.execute('INSERT OR REPLACE INTO events VALUES (?, ?)', (e['id'], json.dumps(e, ensure_ascii=False)))


def log(e, agent, message):
    e['logs'].append({'at': now(), 'agent': agent, 'message': message})


def text(value, label, limit=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise Problem(f'{label}不能为空，且最多 {limit} 个字符')
    return value.strip()


def number(value, label, low, high, integer=False):
    try:
        result = float(value)
        if not low <= result <= high or (integer and result != int(result)):
            raise ValueError()
        return int(result) if integer else result
    except (ValueError, TypeError, OverflowError):
        raise Problem(f'{label}应为 {low} 到 {high} 之间的' + ('整数' if integer else '数字'))


def invoke(e, role, task, context, fallback, tools=None, check=None):
    def audit(run):
        run['scope'] = e.get('_run_scope', 'activity')
        e.setdefault('agent_runs', []).append(run)
        e['agent_runs'] = e['agent_runs'][-100:]
        if DB.exists():
            with sqlite3.connect(DB) as c:
                if c.execute("SELECT 1 FROM sqlite_master WHERE name='agent_runs'").fetchone():
                    c.execute('INSERT INTO agent_runs VALUES (?, ?, ?)', (run['id'], e.get('id'), json.dumps(run, ensure_ascii=False)))
    try:
        return runtime.call(role, task, context, fallback, tools=tools, audit=audit, check=check)
    except runtime.AgentError as ex:
        raise Problem(str(ex))


def tool(description, data):
    return {'description': description, 'data': data}


def feedback_evidence(e):
    return [{'id': 'feedback.' + str(i), 'comment': f['comment'], 'rating': f['rating'], 'phase': f['phase']}
            for i, f in list(enumerate(e['feedback_pool']))[-200:]]


def registration_context(e):
    return {'brief': e['brief'], 'metrics': metrics(e), 'sample_limit': 200,
            'participants': [{'needs': r['needs'], 'question': r['question'], 'source': r['source'], 'college': r['college']}
                             for r in e['registrations'][-200:]]}


class PlanningAgent:
    @staticmethod
    def collect(e, data):
        message = text(data.get('message'), '需求描述', 6000)
        full_history = e.get('planning_messages', [])
        history = full_history[-20:]
        context = {'current_time': now(), 'brief': e['brief'], 'history': history, 'message': message, 'required_fields': FIELDS}
        fallback = {'brief_patch': {}, 'reply': '策划 Agent 尚未配置模型接口，请在下方表单补充信息；已保留你的需求描述。', 'questions': []}
        result = invoke(e, 'planning', 'collect_brief', context, fallback,
                        {'get_event_brief': tool('读取当前活动需求', e['brief'])})
        brief = {**e['brief'], **result['brief_patch']}
        if 'date' in brief:
            try:
                date = datetime.fromisoformat(brief['date'])
                if date.tzinfo is not None:
                    raise ValueError()
            except ValueError:
                raise Problem('模型提取的活动时间无效，请明确提供本地日期与时间')
        if brief != e['brief']:
            if e.get('plan'):
                e['previous_plan'] = e.pop('plan')
            e['state'] = 'DRAFT'
            e['brief'] = brief
        missing = [label for key, label in FIELDS.items() if brief.get(key) is None or str(brief[key]).strip() == '']
        result['missing_fields'] = missing
        e['planning_messages'] = (full_history + [{'role': 'user', 'content': message},
            {'role': 'assistant', 'content': result['reply'], 'questions': result['questions'], 'missing_fields': missing}])[-40:]
        log(e, '策划 Agent', '已处理需求对话' + ('，还需补充：' + '、'.join(missing) if missing else '，基础信息已齐全'))

    @staticmethod
    def generate(e, data):
        missing = [label for key, label in FIELDS.items() if data.get(key) is None or str(data[key]).strip() == '']
        if missing:
            raise Problem('请补充：' + '、'.join(missing))
        base = {key: text(str(data[key]), label, 500) for key, label in FIELDS.items()}
        base['capacity'] = number(data['capacity'], '预计人数', 1, 100000, True)
        base['budget'] = round(number(data['budget'], '预算', 0, 10000000), 2)
        try:
            start = datetime.fromisoformat(base['date'])
            if start.tzinfo is not None:
                raise ValueError()
        except ValueError:
            raise Problem('请输入有效活动时间')
        base['constraints'] = str(data.get('constraints', ''))[:2000]
        base['duration'] = number(data.get('duration', 120), '活动时长', 30, 720, True)
        cap = base['capacity']
        duration = base['duration']
        budget_cents = round(base['budget'] * 100)
        shared_cents = round(budget_cents * .4)
        timeline = [{'id': secrets.token_hex(4), 'time': (start + timedelta(minutes=m)).isoformat(timespec='minutes'), 'title': title, 'owner': base['owner']} for m, title in [(-30, '工作人员就位 / 开放签到'), (0, '主持人开场'), (10, '主题分享'), (round(duration * .55), '互动讨论与问答'), (round(duration * .8), '自由交流'), (duration, '活动结束')]]
        fallback = {
            'summary': f"围绕“{base['objective']}”，面向{base['audience']}组织{base['format']}。由{base['owner']}负责协调场地、参与者和现场分工。" + (f"额外约束待负责人核对落实：{base['constraints']}" if base['constraints'] else ''),
            'timeline': [{k: v for k, v in t.items() if k != 'id'} for t in timeline],
            'preparation': [{'day': day, 'task': task} for day, task in [('T-14', '确认场地、工作人员及活动内容'), ('T-7', '开放报名并发布首轮宣传'), ('T-3', '检查报名进度与物资'), ('T-1', '核对名单、准备参与者提醒'), ('T', '签到与现场执行'), ('T+1', '收集反馈'), ('T+3', '完成复盘及活动总结')]],
            'roles': [{'role': role, 'task': task} for role, task in [('总负责人', '审批方案、预算与现场调整'), ('宣传组', '准备宣传素材并跟进报名'), ('现场组', '场地物资、签到及流程提醒')]],
            'budget': [{'item': item, 'amount': cents / 100} for item, cents in [('场地及设备', shared_cents), ('物资及茶歇', shared_cents), ('应急预留', budget_cents - 2 * shared_cents)]],
            'materials': ['签到名单与二维码', '投影与音响设备', '指示牌、饮用水、文具'],
            'risks': ['提前测试音响与投影，备份演示文件', '人员超额时停止报名；提前核对特殊需求', '嘉宾迟到或流程变更时提交调整建议，负责人确认后生效'],
            'targets': {'registration': cap, 'attendance': max(1, round(cap * .8)), 'attendance_rate': 80, 'feedback': max(1, round(cap * .5)), 'satisfaction': 4.0}}
        previous = e.get('plan') or e.get('previous_plan')
        context = {'brief': base, 'current_plan': previous, 'instruction': str(data.get('instruction', ''))[:6000], 'history': e.get('planning_messages', [])[-20:]}
        result = invoke(e, 'planning', 'generate_plan', context, fallback,
                        {'get_event_brief': tool('读取活动需求', base), 'get_current_plan': tool('读取现有方案', previous)},
                        check=lambda output: validate_plan(output, base))
        for item in result['timeline']:
            item['id'] = secrets.token_hex(4)
        e['brief'], e['plan'] = base, result
        e['state'] = 'WAITING_PLAN_CONFIRMATION'
        e['revision'] += 1
        log(e, '策划 Agent', f"生成第 {e['revision']} 版策划，等待负责人确认")


class RegistrationAgent:
    @staticmethod
    def answer_question(e, data):
        r = next((r for r in e['registrations'] if r['id'] == data.get('ticket')), None)
        if not r or not r['question']:
            raise Problem('没有可处理的报名者问题')
        facts = {k: e['brief'].get(k) for k in ('name', 'objective', 'type', 'format', 'date', 'duration', 'location', 'audience', 'organizer', 'constraints')}
        context = {'facts': facts, 'question': r['question']}
        fallback = {'answer': '', 'needs_human': True, 'reason': '未配置报名 Agent 模型，请负责人根据活动事实答复。', 'evidence': []}
        def check(output):
            fact_text = json.dumps(facts, ensure_ascii=False)
            if not output['needs_human'] and (not output['answer'].strip() or not output['evidence']):
                raise ValueError('直接答复必须包含答案和事实依据')
            if any(quote not in fact_text for quote in output['evidence']):
                raise ValueError('答复依据必须是活动事实中的原文片段')
        r['answer_draft'] = invoke(e, 'registration', 'answer_question', context, fallback,
                                  {'get_event_facts': tool('读取可供报名者查阅的活动事实', facts)}, check)
        log(e, '报名 Agent', '生成答疑草稿，等待负责人确认后对参与者可见')

    @staticmethod
    def analyze(e):
        context = registration_context(e)
        fallback = {'summary': f"当前报名 {len(e['registrations'])} 人，目标 {e['brief']['capacity']} 人。", 'suggestions': ['逐一核对特殊需求和未答复问题。'], 'needs_attention': []}
        e['registration_analysis'] = invoke(e, 'registration', 'analyze_registration', context, fallback,
                                           {'get_registration_summary': tool('读取报名统计及去标识样本', context)})
        log(e, '报名 Agent', '已生成报名进度分析')

    @staticmethod
    def create(e):
        e['registration_path'] = '/join/' + e['id']
        log(e, '报名 Agent', '已创建报名表与参与者入口，宣传确认后开放报名')

    @staticmethod
    def register(e, data):
        if e['state'] != 'REGISTRATION_OPEN':
            raise Problem('当前不在报名阶段')
        if len(e['registrations']) >= e['brief']['capacity']:
            raise Problem('报名名额已满')
        email = text(data.get('email'), '邮箱', 254).lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            raise Problem('邮箱格式不正确')
        if any(r['email'] == email for r in e['registrations']):
            raise Problem('该邮箱已报名，请勿重复提交')
        r = {'id': secrets.token_urlsafe(12), 'name': text(data.get('name'), '姓名', 80), 'email': email,
             'college': text(data.get('college'), '学院', 100), 'grade': str(data.get('grade', ''))[:40],
             'needs': str(data.get('needs', ''))[:1000], 'question': str(data.get('question', ''))[:1000],
             'source': str(data.get('source', '直接访问'))[:100], 'at': now(), 'checked_at': None, 'late': False}
        e['registrations'].append(r)
        log(e, '报名 Agent', '新增报名，当前共 ' + str(len(e['registrations'])) + ' 人')
        return {'ticket': r['id'], 'name': r['name']}


class PublicityAgent:
    @staticmethod
    def generate(e, recap=False, instruction=''):
        b = e['brief']
        if recap:
            s = metrics(e)
            core = f"{b['name']}已结束，共 {s['registration']} 人报名，{s['attendance']} 人到场，收到 {s['feedback']} 份反馈。" + (f"平均满意度 {s['satisfaction']} / 5。" if s['satisfaction'] is not None else '满意度暂缺有效评分。')
        else:
            core = f"{b['name']}\n面向{b['audience']}，一起探索：{b['objective']}。\n时间：{b['date'].replace('T', ' ')}\n地点：{b['location']}\n主办方：{b['organizer']}\n报名入口：{e['registration_path']}"
        fallback = {'article': core + '\n\n' + ('感谢每一位参与者的投入，期待下一次相聚。' if recap else '欢迎带着问题和好奇心前来，与同学们一起交流。'),
                  'group': core + ('\n感谢参与，期待再见！' if recap else '\n欢迎报名参加！'),
                  'schedule': ['T-7 首轮招募', 'T-3 活动亮点与报名进度', 'T-1 活动提醒'] if not recap else ['复盘确认后发布活动总结']}
        context = {'brief': b, 'plan': e.get('approved_plan', e['plan']), 'registration_path': e['registration_path'],
                   'review': e.get('review') if recap else None, 'metrics': metrics(e), 'instruction': str(instruction)[:6000],
                   'current_copy': e.get('recap' if recap else 'publicity')}
        def check(output):
            if not recap and any(e['registration_path'] not in output[k] for k in ('article', 'group')):
                raise ValueError('两个宣传版本都必须保留真实报名路径')
        result = invoke(e, 'publicity', 'generate_recap' if recap else 'generate_publicity', context, fallback,
                        {'get_confirmed_plan': tool('读取已确认策划', context['plan']), 'get_review_data': tool('读取活动复盘及真实统计', {'review': context['review'], 'metrics': context['metrics']})}, check)
        result['approved'] = False
        e['recap' if recap else 'publicity'] = result
        e['state'] = 'WAITING_RECAP_CONFIRMATION' if recap else 'WAITING_PUBLICITY_CONFIRMATION'
        log(e, '宣传 Agent', ('活动总结' if recap else '宣传稿与发布节奏') + '已生成，等待负责人确认')


class OnsiteAgent:
    @staticmethod
    def analyze(e, data):
        if e.get('pending_adjustment'):
            raise Problem('请先处理当前待确认调整，再进行现场分析')
        evidence = feedback_evidence(e)
        context = {'current_time': now(), 'brief': e['brief'], 'timeline': e['plan']['timeline'], 'metrics': metrics(e),
                   'feedback': evidence, 'staff_note': str(data.get('message', ''))[:6000], 'sample_limit': 200}
        fallback = {'summary': '未配置现场模型。请核对签到、反馈及当前时间线。', 'issues': [], 'adjustment': None}
        def check(output):
            ids = {f['id'] for f in evidence}
            if any(ref not in ids for issue in output['issues'] for ref in issue['evidence_ids']):
                raise ValueError('现场分析引用了不存在的反馈')
            if output['adjustment'] and output['adjustment']['item_id'] not in {t['id'] for t in e['plan']['timeline']}:
                raise ValueError('现场建议引用了不存在的时间线环节')
        result = invoke(e, 'onsite', 'analyze_onsite', context, fallback,
                        {'get_live_status': tool('读取现场时间线和统计', context), 'get_live_feedback': tool('读取去标识反馈', evidence)}, check)
        e['onsite_analysis'] = result
        if result['adjustment']:
            e['pending_adjustment'] = result['adjustment']
        log(e, '现场 Agent', '已生成现场分析' + ('，流程调整等待负责人确认' if result['adjustment'] else ''))

    @staticmethod
    def checkin(e, rid):
        if e['state'] != 'LIVE':
            raise Problem('签到尚未开放或已结束')
        r = next((r for r in e['registrations'] if r['id'] == rid), None)
        if not r:
            raise Problem('报名凭证无效')
        if not r['checked_at']:
            r['checked_at'] = now()
            r['late'] = datetime.now() > datetime.fromisoformat(e['brief']['date'])
            log(e, '现场 Agent', '完成一次签到')
        return {'checked_at': r['checked_at'], 'name': r['name']}

    @staticmethod
    def feedback(e, data):
        if e['state'] not in ('LIVE', 'FEEDBACK'):
            raise Problem('当前不在反馈收集阶段')
        rid = data.get('ticket')
        r = next((r for r in e['registrations'] if r['id'] == rid), None)
        if not r or not r['checked_at']:
            raise Problem('请使用已签到的报名凭证提交反馈')
        phase = 'live' if e['state'] == 'LIVE' else 'post'
        rating = number(data.get('rating'), '满意度', 1, 5, True) if data.get('rating') else None
        feedback = {'ticket': rid, 'phase': phase, 'rating': rating, 'comment': text(data.get('comment'), '反馈', 2000), 'at': now()}
        existing = next((f for f in e['feedback_pool'] if f['ticket'] == rid and f['phase'] == phase), None)
        if existing:
            existing.update(feedback)
        else:
            e['feedback_pool'].append(feedback)
        log(e, '现场 Agent', '收到参与者反馈')
        return {'ok': True}


def metrics(e):
    registered = len(e['registrations'])
    attended = sum(bool(r['checked_at']) for r in e['registrations'])
    ratings = {}
    for f in e['feedback_pool']:
        if f['rating'] is not None:
            ratings[f['ticket']] = f['rating']
    return {'registration': registered, 'attendance': attended, 'attendance_rate': round(attended / registered * 100, 1) if registered else None,
            'feedback': len({f['ticket'] for f in e['feedback_pool']}), 'satisfaction': round(sum(ratings.values()) / len(ratings), 2) if ratings else None, 'rating_count': len(ratings)}


class ReviewAgent:
    @staticmethod
    def generate(e):
        s = metrics(e)
        targets = e['plan']['targets']
        comparison = [{'key': key, 'target': target, 'actual': s[key], 'met': s[key] >= target if s[key] is not None else None} for key, target in targets.items()]
        suggestions = []
        if s['registration'] < targets['registration']:
            suggestions.append('报名未达目标：下次在 T-3 检查各渠道转化，并由负责人确认补充宣传。')
        if s['attendance_rate'] is not None and s['attendance_rate'] < 80:
            suggestions.append('到场率低于目标：下次在 T-1 核实参加意向，并在开始前一小时发送提醒。')
        if s['feedback'] < targets['feedback']:
            suggestions.append('反馈样本不足：下次将反馈入口放在结束页，并在离场前预留两分钟填写。')
        if not suggestions:
            suggestions.append('保留本次筹备节奏；下次逐项核对参与者意见，并明确改进责任人。')
        evidence = feedback_evidence(e) + [{'id': 'metrics.' + key, 'value': value} for key, value in s.items()] + [{'id': 'adjustment.' + str(i), **a} for i, a in enumerate(e['adjustments'])]
        context = {'brief': e['brief'], 'original_plan': e.get('approved_plan'), 'executed_timeline': e['plan']['timeline'],
                   'publicity': e.get('publicity'), 'metrics': s, 'targets': targets, 'comparison': comparison, 'evidence': evidence, 'feedback_sample_limit': 200}
        fallback = {'summary': f"本次活动共 {s['registration']} 人报名、{s['attendance']} 人到场，收到 {s['feedback']} 位参与者的反馈。评分样本 {s['rating_count']} 份。", 'suggestions': suggestions, 'findings': []}
        def check(output):
            ids = {item['id'] for item in evidence}
            if any(ref not in ids for finding in output['findings'] for ref in finding['evidence_ids']):
                raise ValueError('复盘引用了不存在的证据')
        result = invoke(e, 'review', 'generate_review', context, fallback,
                        {'get_review_data': tool('读取复盘数据和证据', context)}, check)
        report = {**result, 'metrics': s, 'comparison': comparison, 'generated_at': now(), 'approved': False}
        e['review'] = report
        e['state'] = 'WAITING_REVIEW_CONFIRMATION'
        log(e, '复盘 Agent', '已汇总真实报名、签到和去重反馈数据，等待确认')


class Orchestrator:
    ALLOWED = {
        'planning_chat': ['DRAFT', 'WAITING_PLAN_CONFIRMATION'],
        'plan_from_brief': ['DRAFT', 'WAITING_PLAN_CONFIRMATION'],
        'analyze_registration': ['REGISTRATION_OPEN', 'LIVE', 'FEEDBACK'],
        'answer_question': ['REGISTRATION_OPEN', 'LIVE', 'FEEDBACK'],
        'analyze_onsite': ['LIVE'],
        'regenerate_recap': ['WAITING_RECAP_CONFIRMATION'],
        'plan': ['DRAFT', 'WAITING_PLAN_CONFIRMATION'], 'edit_plan': ['WAITING_PLAN_CONFIRMATION'], 'confirm_plan': ['WAITING_PLAN_CONFIRMATION'],
        'publicity': ['PLAN_CONFIRMED', 'WAITING_PUBLICITY_CONFIRMATION'], 'edit_publicity': ['WAITING_PUBLICITY_CONFIRMATION'],
        'confirm_publicity': ['WAITING_PUBLICITY_CONFIRMATION'], 'start': ['REGISTRATION_OPEN'],
        'checkin': ['LIVE'], 'adjust': ['LIVE'], 'approve_adjustment': ['LIVE'], 'reject_adjustment': ['LIVE'],
        'finish': ['LIVE'], 'review': ['FEEDBACK', 'WAITING_REVIEW_CONFIRMATION'],
        'confirm_review': ['WAITING_REVIEW_CONFIRMATION'], 'edit_recap': ['WAITING_RECAP_CONFIRMATION'],
        'confirm_recap': ['WAITING_RECAP_CONFIRMATION'], 'answer': ['REGISTRATION_OPEN', 'LIVE', 'FEEDBACK']}

    @staticmethod
    def act(e, action, data):
        if action not in Orchestrator.ALLOWED or e['state'] not in Orchestrator.ALLOWED[action]:
            raise Problem('当前阶段不允许此操作，请刷新活动状态')
        if action == 'planning_chat':
            PlanningAgent.collect(e, data)
        elif action == 'plan_from_brief':
            PlanningAgent.generate(e, {**e['brief'], 'instruction': data.get('instruction', '')})
        elif action == 'analyze_registration':
            RegistrationAgent.analyze(e)
        elif action == 'answer_question':
            RegistrationAgent.answer_question(e, data)
        elif action == 'analyze_onsite':
            OnsiteAgent.analyze(e, data)
        elif action == 'regenerate_recap':
            PublicityAgent.generate(e, recap=True, instruction=data.get('instruction', ''))
        elif action == 'plan':
            PlanningAgent.generate(e, data)
        elif action == 'edit_plan':
            e['plan']['summary'] = text(data.get('summary'), '方案正文', 30000)
            e['revision'] += 1
            log(e, '策划 Agent', '负责人修改方案正文，等待确认')
        elif action == 'confirm_plan':
            e['state'] = 'PLAN_CONFIRMED'
            e['approved_plan'] = json.loads(json.dumps(e['plan']))
            log(e, '总控 Agent', '负责人确认策划第 ' + str(e['revision']) + ' 版')
            RegistrationAgent.create(e)
        elif action == 'publicity':
            PublicityAgent.generate(e, instruction=data.get('instruction', ''))
        elif action in ('edit_publicity', 'edit_recap'):
            key = 'recap' if action == 'edit_recap' else 'publicity'
            for field in ('article', 'group'):
                e[key][field] = text(data.get(field), '文案', 30000)
            log(e, '宣传 Agent', '负责人更新待确认文案')
        elif action == 'confirm_publicity':
            e['publicity']['approved'] = True
            e['state'] = 'REGISTRATION_OPEN'
            log(e, '总控 Agent', '负责人确认宣传，已开放本站报名；外部渠道需手动发布')
        elif action == 'start':
            e['state'] = 'LIVE'
            log(e, '现场 Agent', '负责人开启现场，报名关闭，签到开放')
        elif action == 'checkin':
            OnsiteAgent.checkin(e, data.get('ticket'))
        elif action == 'adjust':
            if e.get('pending_adjustment'):
                raise Problem('请先处理当前待确认的调整')
            mins = number(data.get('minutes'), '延后分钟数', 1, 180, True)
            item_id = data.get('item_id')
            if not any(t['id'] == item_id for t in e['plan']['timeline']):
                raise Problem('请选择调整起点')
            e['pending_adjustment'] = {'minutes': mins, 'item_id': item_id, 'reason': text(data.get('reason'), '调整原因', 1000)}
            log(e, '现场 Agent', '提出时间线调整建议，待负责人确认')
        elif action == 'approve_adjustment':
            pending = e.get('pending_adjustment')
            if not pending:
                raise Problem('没有待确认调整')
            active = False
            for t in e['plan']['timeline']:
                active = active or t['id'] == pending['item_id']
                if active:
                    t['time'] = (datetime.fromisoformat(t['time']) + timedelta(minutes=pending['minutes'])).isoformat(timespec='minutes')
            e['adjustments'].append({**pending, 'at': now()})
            e['pending_adjustment'] = None
            log(e, '总控 Agent', '负责人批准流程调整：' + pending['reason'])
        elif action == 'reject_adjustment':
            e['pending_adjustment'] = None
            log(e, '总控 Agent', '负责人拒绝流程调整')
        elif action == 'finish':
            if e.get('pending_adjustment'):
                raise Problem('请先处理待确认流程调整')
            e['state'] = 'FEEDBACK'
            log(e, '现场 Agent', '活动结束，开放活动后反馈')
        elif action == 'review':
            ReviewAgent.generate(e)
        elif action == 'confirm_review':
            e['review']['approved'] = True
            log(e, '总控 Agent', '负责人确认复盘，反馈收集关闭')
            PublicityAgent.generate(e, recap=True)
        elif action == 'confirm_recap':
            e['recap']['approved'] = True
            e['state'] = 'COMPLETED'
            log(e, '总控 Agent', '负责人确认总结，活动归档；外部渠道需手动发布')
        elif action == 'answer':
            rid = data.get('ticket')
            r = next((r for r in e['registrations'] if r['id'] == rid), None)
            if not r:
                raise Problem('报名记录不存在')
            r['answer'] = text(data.get('answer'), '答复', 5000)
            log(e, '报名 Agent', '负责人回复参与者提问，参与者可凭报名凭证查看')


def new_event(name='未命名活动'):
    e = {'id': secrets.token_urlsafe(9), 'state': 'DRAFT', 'brief': {'name': text(name, '活动名称', 500)}, 'revision': 0,
         'registrations': [], 'feedback_pool': [], 'logs': [], 'adjustments': [], 'created_at': now()}
    log(e, '总控 Agent', '创建活动，等待补充策划信息')
    return e


def public_event(e):
    return {'id': e['id'], 'state': e['state'], 'brief': {k: e['brief'].get(k) for k in ['name', 'objective', 'date', 'location', 'audience', 'capacity', 'organizer']},
            'remaining': max(0, e['brief'].get('capacity', 0) - len(e['registrations'])),
            'publicity': e.get('publicity', {}).get('article') if e.get('publicity', {}).get('approved') else None}


def run_playground(role, request):
    task = request.get('task')
    data = request.get('input')
    playground.validate_input(role, task, data)
    message = request.get('message', '')
    if not isinstance(message, str) or len(message) > 6000:
        raise Problem('测试补充要求最多 6000 个字符')
    # Scratch context never receives a real event ID and is never passed to save().
    e = {'state': 'DRAFT', 'brief': data['brief'], 'revision': 0, 'logs': [], 'registrations': [],
         'feedback_pool': [], 'adjustments': [], '_run_scope': 'playground'}
    if 'plan' in data:
        e['plan'] = data['plan']
        e['approved_plan'] = data['plan']
    e['registration_path'] = data.get('registration_path', '/join/example-preview')
    for i, r in enumerate(data.get('participants', [])):
        e['registrations'].append({**r, 'id': 'sample-'+str(i), 'checked_at': now() if r['checked_in'] else None})
    for f in data.get('feedback', []):
        e['feedback_pool'].append({**f, 'ticket': 'sample-'+str(int(f['participant_index'])), 'at': now()})
    if task == 'collect_brief':
        e['planning_messages'] = data['history']
        PlanningAgent.collect(e, {'message': message})
        answer = e['planning_messages'][-1]
        result = {'brief': e['brief'], 'reply': answer['content'], 'questions': answer['questions'], 'missing_fields': answer['missing_fields']}
        next_input = {'brief': e['brief'], 'history': [{k: m[k] for k in ('role', 'content')} for m in e['planning_messages']]}
    elif task == 'generate_plan':
        PlanningAgent.generate(e, {**data['brief'], 'instruction': message})
        result = e['plan']
    elif task in ('generate_publicity', 'generate_recap'):
        if task == 'generate_recap':
            e['review'] = {'summary': '独立测试中的示例复盘数据', 'metrics': metrics(e), 'approved': True}
        PublicityAgent.generate(e, recap=task == 'generate_recap', instruction=message)
        result = e['recap' if task == 'generate_recap' else 'publicity']
    elif task == 'answer_question':
        e['registrations'] = [{'id': 'sample-question', 'question': data['question']}]
        RegistrationAgent.answer_question(e, {'ticket': 'sample-question'})
        result = e['registrations'][0]['answer_draft']
    elif task == 'analyze_registration':
        RegistrationAgent.analyze(e)
        result = e['registration_analysis']
    elif task == 'analyze_onsite':
        OnsiteAgent.analyze(e, {'message': message})
        result = e['onsite_analysis']
    elif task == 'generate_review':
        ReviewAgent.generate(e)
        result = e['review']
    return {'role': role, 'task': task, 'result': result, 'run': e['agent_runs'][-1],
            'next_input': next_input if task == 'collect_brief' else data, 'persisted_to_event': False}


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, content_type='application/json; charset=utf-8'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Cache-Control', 'no-store' if content_type.startswith('application/json') else 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        return secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + admin_token())

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == '/api/health':
                modes = {item['mode'] for item in runtime.status().values()}
                return self.send(200, {'ok': True, 'mode': next(iter(modes)) if len(modes) == 1 else 'mixed',
                                       'public_base_url': getattr(self.server, 'public_base_url', '')})
            if path.startswith('/api/public/'):
                return self.send(200, public_event(load(path.rsplit('/', 1)[1])))
            if path.startswith('/api/'):
                if not self.authorized():
                    return self.send(401, {'error': '请输入负责人访问密钥'})
                if path == '/api/agents':
                    return self.send(200, runtime.status())
                lab = re.fullmatch(r'/api/agents/(planning|publicity|registration|onsite|review)/playground', path)
                if lab:
                    role = lab[1]
                    return self.send(200, {'role': role, 'config': runtime.status()[role],
                        'tasks': [{'id': task, 'name': name, **playground.example(task)} for task, name in playground.TASKS[role].items()]})
                if path == '/api/agent-runs':
                    with sqlite3.connect(DB) as c:
                        runs = [dict(json.loads(row[1]), event_id=row[0]) for row in c.execute('SELECT event_id, data FROM agent_runs ORDER BY rowid DESC LIMIT 100')]
                    return self.send(200, runs)
                if path == '/api/events':
                    with sqlite3.connect(DB) as c:
                        events = [json.loads(r[0]) for r in c.execute('SELECT data FROM events')]
                    return self.send(200, sorted([dict(e, metrics=metrics(e)) for e in events], key=lambda e: e['created_at'], reverse=True))
                match = re.fullmatch(r'/api/events/([\w-]+)(/export)?', path)
                if match:
                    e = load(match[1])
                    if match[2]:
                        stream = io.StringIO()
                        writer = csv.writer(stream)
                        writer.writerow(['姓名', '邮箱', '学院', '年级', '需求', '报名时间', '签到时间'])
                        for r in e['registrations']:
                            vals = [str(r.get(k) or '') for k in ['name', 'email', 'college', 'grade', 'needs', 'at', 'checked_at']]
                            writer.writerow(["'" + v if v.lstrip().startswith(('=', '+', '-', '@')) else v for v in vals])
                        return self.send(200, '\ufeff' + stream.getvalue(), 'text/csv; charset=utf-8')
                    return self.send(200, dict(e, metrics=metrics(e)))
                return self.send(404, {'error': '接口不存在'})
            if re.fullmatch(r'/agents/(planning|publicity|registration|onsite|review)', path):
                filename = 'agent-lab.html'
            else:
                filename = 'index.html' if path == '/' or path.startswith('/join/') else path.removeprefix('/static/')
            target = (ROOT / 'static' / filename).resolve()
            if not target.is_relative_to(ROOT / 'static') or not target.is_file():
                return self.send(404, 'Not found', 'text/plain')
            types = {'.html': 'text/html; charset=utf-8', '.js': 'application/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.jpg': 'image/jpeg', '.png': 'image/png'}
            self.send(200, target.read_bytes(), types.get(target.suffix, 'application/octet-stream'))
        except Problem as ex:
            self.send(404, {'error': str(ex)})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 100000:
                raise Problem('请求大小无效')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise Problem('请求必须为 JSON 对象')
            public = re.fullmatch(r'/api/public/([\w-]+)/(register|checkin|feedback|ticket)', path)
            if not public and not self.authorized():
                return self.send(401, {'error': '请输入负责人访问密钥'})
            lab = re.fullmatch(r'/api/agents/(planning|publicity|registration|onsite|review)/playground', path)
            if lab:
                try:
                    return self.send(200, run_playground(lab[1], data))
                except (Problem, runtime.AgentError, ValueError, TypeError) as ex:
                    return self.send(400, {'error': str(ex)})
            test = re.fullmatch(r'/api/agents/(planning|publicity|registration|onsite|review)/test', path)
            if test:
                if runtime.settings(test[1])['mode'] != 'model':
                    raise Problem('该 Agent 尚未配置模型接口，不能执行连通测试')
                result = invoke({'_run_scope': 'connection'}, test[1], 'connection_test', {'instruction': '连通测试，请返回 {"ok":true}'}, {'ok': True})
                return self.send(200, result)
            with LOCK:
                if public:
                    eid, action = public.groups()
                    e = load(eid)
                    if action == 'register':
                        result = RegistrationAgent.register(e, data)
                    elif action == 'checkin':
                        result = OnsiteAgent.checkin(e, data.get('ticket'))
                    elif action == 'feedback':
                        result = OnsiteAgent.feedback(e, data)
                    else:
                        r = next((r for r in e['registrations'] if r['id'] == data.get('ticket')), None)
                        if not r:
                            raise Problem('报名凭证无效')
                        return self.send(200, {'name': r['name'], 'checked_at': r['checked_at'], 'answer': r.get('answer'), 'question': r['question']})
                    save(e)
                    return self.send(200, result)
                if path == '/api/events':
                    e = new_event(data.get('name', '未命名活动'))
                    save(e)
                    return self.send(201, dict(e, metrics=metrics(e)))
                match = re.fullmatch(r'/api/events/([\w-]+)/actions/([a-z_]+)', path)
                if not match:
                    return self.send(404, {'error': '接口不存在'})
                e = load(match[1])
                if data.get('expected_version') != e.get('version'):
                    raise Problem('活动数据已更新，请刷新并重新核对后操作')
                version = e.get('version')
            # Model calls run outside the write lock so public check-ins never wait for inference.
            Orchestrator.act(e, match[2], data)
            with LOCK:
                if load(e['id']).get('version') != version:
                    return self.send(409, {'error': '生成期间活动数据发生变化，本次结果未写入，请刷新后重试'})
                save(e)
                self.send(200, dict(e, metrics=metrics(e)))
        except (Problem, runtime.AgentError, ValueError, TypeError) as ex:
            self.send(400, {'error': str(ex)})
        except Exception:
            self.send(500, {'error': '服务内部错误，本次操作未完成'})
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--public-base-url', default='', help='Participant-facing HTTP(S) origin for links and QR codes')
    parser.add_argument('--demo', action='store_true', help='Create one example plan when the database is empty')
    args = parser.parse_args()
    if args.public_base_url:
        origin = urlparse(args.public_base_url)
        if origin.scheme not in ('http', 'https') or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment or origin.path not in ('', '/'):
            parser.error('--public-base-url must be an HTTP(S) origin without credentials, path, query or fragment')
    init_db()
    if args.demo:
        with sqlite3.connect(DB) as c:
            empty_db = c.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 0
        if empty_db:
            demo = new_event('AI 创新交流夜（示例）')
            demo_date = (datetime.now() + timedelta(days=7)).replace(hour=19, minute=0, second=0, microsecond=0)
            PlanningAgent.generate(demo, {'name': 'AI 创新交流夜（示例）', 'objective': '认识 AI Agent 的实际应用，促进跨学院交流',
                'type': '交流分享', 'level': '校级', 'format': '线下分享与互动讨论', 'date': demo_date.isoformat(timespec='minutes'),
                'location': '大学生活动中心 · 201 报告厅', 'audience': '全校对 AI 感兴趣的同学', 'capacity': 100, 'budget': 1200,
                'organizer': '学生科技协会', 'owner': '活动负责人', 'duration': 120, 'constraints': '21:00 前结束；欢迎零基础同学参加。'})
            save(demo)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.public_base_url = args.public_base_url.rstrip('/')
    print(f'Campus Events: http://{args.host}:{args.port}/#key={admin_token()}', flush=True)
    server.serve_forever()
