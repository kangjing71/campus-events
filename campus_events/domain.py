"""Domain logic for campus events: agents and orchestration."""
import json
import re
import secrets
from datetime import datetime, timedelta
from agents import runtime
from agents.agent import Agent
from agents.contracts import validate_plan
from . import store
from .store import Problem, now

FIELDS = {'name': '活动名称', 'objective': '活动目标', 'type': '活动类型', 'level': '活动级别', 'format': '活动形式', 'date': '活动时间', 'location': '活动地点', 'audience': '目标参与者', 'capacity': '预计人数', 'budget': '预算', 'organizer': '主办方', 'owner': '负责人'}
REQUIRED = ('name', 'type', 'format', 'audience', 'date', 'location', 'capacity', 'budget')
STATES = ['DRAFT', 'WAITING_PLAN_CONFIRMATION', 'PLAN_CONFIRMED', 'WAITING_PUBLICITY_CONFIRMATION', 'REGISTRATION_OPEN', 'LIVE', 'FEEDBACK', 'WAITING_REVIEW_CONFIRMATION', 'WAITING_RECAP_CONFIRMATION', 'COMPLETED']


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


def make_audit(e):
    def audit(run):
        run['scope'] = e.get('_run_scope', 'activity')
        e.setdefault('agent_runs', []).append(run)
        e['agent_runs'] = e['agent_runs'][-100:]
        if store.DB.exists():
            with store.sqlite3.connect(store.DB) as c:
                if c.execute("SELECT 1 FROM sqlite_master WHERE name='agent_runs'").fetchone():
                    c.execute('INSERT INTO agent_runs VALUES (?, ?, ?)', (run['id'], e.get('id'), json.dumps(run, ensure_ascii=False)))
    return audit


def invoke(e, role, task, context, fallback, tools=None, check=None):
    try:
        return runtime.call(role, task, context, fallback, tools=tools, audit=make_audit(e), check=check)
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
    def _collect_inputs(e, message):
        full_history = e.get('planning_messages', [])
        history = full_history[-20:]
        context = {'current_time': now(), 'brief': e['brief'], 'history': history, 'message': message, 'required_fields': {k: FIELDS[k] for k in REQUIRED}}
        fallback = {'brief_patch': {}, 'reply': '策划 Agent 尚未配置模型接口，请在下方表单补充信息；已保留你的需求描述。', 'questions': []}
        return context, fallback, {'get_event_brief': tool('读取当前活动需求', e['brief'])}

    @staticmethod
    def _apply_collect(e, message, result):
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
        missing = [FIELDS[key] for key in REQUIRED if brief.get(key) is None or str(brief[key]).strip() == '']
        result['missing_fields'] = missing
        e['planning_messages'] = (e.get('planning_messages', []) + [{'role': 'user', 'content': message},
            {'role': 'assistant', 'content': result['reply'], 'questions': result['questions'], 'missing_fields': missing}])[-40:]
        log(e, '策划', '已处理需求对话' + ('，还需补充：' + '、'.join(missing) if missing else '，基础信息已齐全'))

    @staticmethod
    def collect(e, data):
        message = text(data.get('message'), '需求描述', 6000)
        context, fallback, tools = PlanningAgent._collect_inputs(e, message)
        result = invoke(e, 'planning', 'collect_brief', context, fallback, tools)
        PlanningAgent._apply_collect(e, message, result)

    @staticmethod
    def stream_collect(e, data):
        """collect 的流式版本：产出 delta/tool/error 事件，result 落地后由调用方保存。

        成功后 e 的修改与 collect() 完全一致（planning_messages、brief、state、日志）。
        """
        message = text(data.get('message'), '需求描述', 6000)
        context, _, tools = PlanningAgent._collect_inputs(e, message)
        agent = Agent('planning', tools=tools)
        result = None
        for event in agent.stream('collect_brief', context, audit=make_audit(e)):
            if event['type'] == 'result':
                result = event['value']
            else:
                yield event
        if result is None:
            return
        try:
            PlanningAgent._apply_collect(e, message, result)
        except Problem as ex:
            yield {'type': 'error', 'message': str(ex)}

    @staticmethod
    def generate(e, data):
        missing = [FIELDS[key] for key in REQUIRED if data.get(key) is None or str(data[key]).strip() == '']
        if missing:
            raise Problem('请补充：' + '、'.join(missing))
        base = {key: text(str(data[key]), label, 500) for key, label in FIELDS.items() if key in REQUIRED}
        base['objective'] = str(data.get('objective') or '')[:500]
        base['level'] = str(data.get('level') or '')[:100]
        base['organizer'] = str(data.get('organizer') or '')[:200]
        base['owner'] = str(data.get('owner') or '活动负责人')[:100]
        base['capacity'] = number(data['capacity'], '预计人数', 1, 100000, True)
        base['budget'] = round(number(data['budget'], '预算', 0, 10000000), 2)
        try:
            start = datetime.fromisoformat(base['date'])
            if start.tzinfo is not None:
                raise ValueError()
        except ValueError:
            raise Problem('请输入有效活动时间')
        base['constraints'] = str(data.get('constraints', ''))[:2000]
        if data.get('duration') is None or str(data.get('duration')).strip() == '':
            raise Problem('请补充：活动时长')
        base['duration'] = number(data['duration'], '活动时长', 30, 720, True)
        cap = base['capacity']
        duration = base['duration']
        budget_cents = round(base['budget'] * 100)
        shared_cents = round(budget_cents * .4)
        timeline = [{'id': secrets.token_hex(4), 'time': (start + timedelta(minutes=m)).isoformat(timespec='minutes'), 'title': title, 'owner': base['owner']} for m, title in [(-30, '工作人员就位 / 开放签到'), (0, '主持人开场'), (10, '主题分享'), (round(duration * .55), '互动讨论与问答'), (round(duration * .8), '自由交流'), (duration, '活动结束')]]
        fallback = {
            'summary': f"围绕“{base['objective'] or base['name']}”，面向{base['audience']}组织{base['format']}。由{base['owner']}负责协调场地、参与者和现场分工。" + (f"额外约束待负责人核对落实：{base['constraints']}" if base['constraints'] else ''),
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
        log(e, '策划', f"生成第 {e['revision']} 版策划，等待负责人确认")


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
        log(e, '报名', '生成答疑草稿，等待负责人确认后对参与者可见')

    @staticmethod
    def analyze(e):
        context = registration_context(e)
        fallback = {'summary': f"当前报名 {len(e['registrations'])} 人，目标 {e['brief']['capacity']} 人。", 'suggestions': ['逐一核对特殊需求和未答复问题。'], 'needs_attention': []}
        e['registration_analysis'] = invoke(e, 'registration', 'analyze_registration', context, fallback,
                                           {'get_registration_summary': tool('读取报名统计及去标识样本', context)})
        log(e, '报名', '已生成报名进度分析')

    @staticmethod
    def create(e):
        e['registration_path'] = '/join/' + e['id']
        log(e, '报名', '已创建报名表与参与者入口，宣传确认后开放报名')

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
        log(e, '报名', '新增报名，当前共 ' + str(len(e['registrations'])) + ' 人')
        return {'ticket': r['id'], 'name': r['name']}


class PublicityAgent:
    @staticmethod
    def generate(e, recap=False, instruction=''):
        b = e['brief']
        if recap:
            s = metrics(e)
            core = f"{b['name']}已结束，共 {s['registration']} 人报名，{s['attendance']} 人到场，收到 {s['feedback']} 份反馈。" + (f"平均满意度 {s['satisfaction']} / 5。" if s['satisfaction'] is not None else '满意度暂缺有效评分。')
        else:
            core = f"{b['name']}\n面向{b['audience']}，一起探索：{b.get('objective') or b['name']}。\n时间：{b['date'].replace('T', ' ')}\n地点：{b['location']}\n主办方：{b.get('organizer') or '待定'}\n报名入口：{e['registration_path']}"
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
        log(e, '宣传', ('活动总结' if recap else '宣传稿与发布节奏') + '已生成，等待负责人确认')


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
        log(e, '现场', '已生成现场分析' + ('，流程调整等待负责人确认' if result['adjustment'] else ''))

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
            log(e, '现场', '完成一次签到')
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
        log(e, '现场', '收到参与者反馈')
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
        log(e, '复盘', '已汇总真实报名、签到和去重反馈数据，等待确认')


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
            log(e, '策划', '负责人修改方案正文，等待确认')
        elif action == 'confirm_plan':
            e['state'] = 'PLAN_CONFIRMED'
            e['approved_plan'] = json.loads(json.dumps(e['plan']))
            log(e, '总控', '负责人确认策划第 ' + str(e['revision']) + ' 版')
            RegistrationAgent.create(e)
        elif action == 'publicity':
            PublicityAgent.generate(e, instruction=data.get('instruction', ''))
        elif action in ('edit_publicity', 'edit_recap'):
            key = 'recap' if action == 'edit_recap' else 'publicity'
            for field in ('article', 'group'):
                e[key][field] = text(data.get(field), '文案', 30000)
            log(e, '宣传', '负责人更新待确认文案')
        elif action == 'confirm_publicity':
            e['publicity']['approved'] = True
            e['state'] = 'REGISTRATION_OPEN'
            log(e, '总控', '负责人确认宣传，已开放本站报名；外部渠道需手动发布')
        elif action == 'start':
            e['state'] = 'LIVE'
            log(e, '现场', '负责人开启现场，报名关闭，签到开放')
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
            log(e, '现场', '提出时间线调整建议，待负责人确认')
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
            log(e, '总控', '负责人批准流程调整：' + pending['reason'])
        elif action == 'reject_adjustment':
            e['pending_adjustment'] = None
            log(e, '总控', '负责人拒绝流程调整')
        elif action == 'finish':
            if e.get('pending_adjustment'):
                raise Problem('请先处理待确认流程调整')
            e['state'] = 'FEEDBACK'
            log(e, '现场', '活动结束，开放活动后反馈')
        elif action == 'review':
            ReviewAgent.generate(e)
        elif action == 'confirm_review':
            e['review']['approved'] = True
            log(e, '总控', '负责人确认复盘，反馈收集关闭')
            PublicityAgent.generate(e, recap=True)
        elif action == 'confirm_recap':
            e['recap']['approved'] = True
            e['state'] = 'COMPLETED'
            log(e, '总控', '负责人确认总结，活动归档；外部渠道需手动发布')
        elif action == 'answer':
            rid = data.get('ticket')
            r = next((r for r in e['registrations'] if r['id'] == rid), None)
            if not r:
                raise Problem('报名记录不存在')
            r['answer'] = text(data.get('answer'), '答复', 5000)
            log(e, '报名', '负责人回复参与者提问，参与者可凭报名凭证查看')


def new_event(name='未命名活动'):
    e = {'id': secrets.token_urlsafe(9), 'state': 'DRAFT', 'brief': {'name': text(name, '活动名称', 500)}, 'revision': 0,
         'registrations': [], 'feedback_pool': [], 'logs': [], 'adjustments': [], 'created_at': now()}
    log(e, '总控', '创建活动，等待补充策划信息')
    return e


def public_event(e):
    return {'id': e['id'], 'state': e['state'], 'brief': {k: e['brief'].get(k) for k in ['name', 'objective', 'date', 'location', 'audience', 'capacity', 'organizer']},
            'remaining': max(0, e['brief'].get('capacity', 0) - len(e['registrations'])),
            'publicity': e.get('publicity', {}).get('article') if e.get('publicity', {}).get('approved') else None}

