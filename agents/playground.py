"""Isolated fixtures and input contracts for testing one business role at a time."""
import copy
import json
from datetime import datetime, timedelta
from jsonschema import Draft202012Validator
from .contracts import BRIEF_FIELDS, PLAN, array, numeric, obj, string

TASKS = {
    'planning': {'collect_brief': '需求理解与补问', 'generate_plan': '完整活动策划'},
    'publicity': {'generate_publicity': '活动招募宣传', 'generate_recap': '活动总结宣传'},
    'registration': {'answer_question': '报名者问题答复', 'analyze_registration': '报名情况分析'},
    'onsite': {'analyze_onsite': '现场反馈与异常建议'},
    'review': {'generate_review': '活动复盘与改进建议'},
}

PARTICIPANT = obj({'college': string(100), 'source': string(100), 'needs': string(1000, True),
                   'question': string(1000, True), 'checked_in': {'type': 'boolean'}})
FEEDBACK = obj({'participant_index': numeric(0, 49, True), 'comment': string(2000),
                'rating': {'anyOf': [numeric(1, 5, True), {'type': 'null'}]}, 'phase': {'enum': ['live', 'post']}})
HISTORY = array(obj({'role': {'enum': ['user', 'assistant']}, 'content': string(6000)}), 0, 40)
PLAN_INPUT = copy.deepcopy(PLAN)
PLAN_INPUT['properties']['timeline']['items']['properties']['id'] = string(100)
PLAN_INPUT['properties']['timeline']['items']['required'].append('id')
INPUTS = {
    'collect_brief': obj({'brief': obj(BRIEF_FIELDS, []), 'history': HISTORY}),
    'generate_plan': obj({'brief': obj(BRIEF_FIELDS)}),
    'generate_publicity': obj({'brief': obj(BRIEF_FIELDS), 'plan': PLAN_INPUT, 'registration_path': string(500)}),
    'generate_recap': obj({'brief': obj(BRIEF_FIELDS), 'plan': PLAN_INPUT, 'participants': array(PARTICIPANT, 0, 50), 'feedback': array(FEEDBACK, 0, 100)}),
    'answer_question': obj({'brief': obj(BRIEF_FIELDS), 'question': string(1000)}),
    'analyze_registration': obj({'brief': obj(BRIEF_FIELDS), 'participants': array(PARTICIPANT, 0, 50)}),
    'analyze_onsite': obj({'brief': obj(BRIEF_FIELDS), 'plan': PLAN_INPUT, 'participants': array(PARTICIPANT, 0, 50), 'feedback': array(FEEDBACK, 0, 100)}),
    'generate_review': obj({'brief': obj(BRIEF_FIELDS), 'plan': PLAN_INPUT, 'participants': array(PARTICIPANT, 0, 50), 'feedback': array(FEEDBACK, 0, 100)}),
}


def example(task):
    start = (datetime.now() + timedelta(days=7)).replace(hour=19, minute=0, second=0, microsecond=0)
    brief = {'name': '校园 AI 交流夜（测试样例）', 'objective': '交流 AI 应用经验', 'type': '交流分享', 'level': '校级',
             'format': '线下分享与讨论', 'date': start.isoformat(timespec='minutes'), 'location': '大学生活动中心 201',
             'audience': '全校学生', 'organizer': '学生科技协会', 'owner': '示例负责人', 'capacity': 100, 'budget': 1200,
             'duration': 120, 'constraints': '21:00 前结束；无需携带电脑；欢迎零基础同学。'}
    plan = {'summary': '测试样例：通过分享和讨论促进跨学院交流。',
            'timeline': [{'id': 'slot-'+str(i), 'time': (start+timedelta(minutes=m)).isoformat(timespec='minutes'), 'title': title, 'owner': brief['owner']}
                         for i, (m, title) in enumerate([(-30, '开放签到'), (0, '开场'), (10, '主题分享'), (70, '互动讨论'), (120, '活动结束')])],
            'preparation': [{'day': 'T-7', 'task': '发布招募'}, {'day': 'T-1', 'task': '确认到场'}],
            'roles': [{'role': '现场组', 'task': '签到和流程协调'}], 'budget': [{'item': '物资及设备', 'amount': 1200}],
            'materials': ['话筒', '投影仪'], 'risks': ['嘉宾迟到时由负责人确认调整'],
            'targets': {'registration': 100, 'attendance': 80, 'attendance_rate': 80, 'feedback': 50, 'satisfaction': 4}}
    participants = [
        {'college': '计算机学院', 'source': '微信群', 'needs': '', 'question': '要带电脑吗？', 'checked_in': True},
        {'college': '设计学院', 'source': '微信公众号', 'needs': '希望有无障碍座位', 'question': '', 'checked_in': True},
        {'college': '管理学院', 'source': '朋友圈', 'needs': '', 'question': '零基础可以参加吗？', 'checked_in': False}]
    feedback = [{'participant_index': 0, 'comment': '希望讨论时间更长一点', 'rating': 4, 'phase': 'live'},
                {'participant_index': 1, 'comment': '案例很有帮助', 'rating': 5, 'phase': 'post'}]
    common = {'brief': brief, 'plan': plan, 'participants': participants, 'feedback': feedback,
              'question': '需要带电脑吗？', 'registration_path': '/join/example-preview'}
    if task == 'collect_brief':
        data = {'brief': {'name': '待定活动'}, 'history': []}
    else:
        data = {key: copy.deepcopy(common[key]) for key in INPUTS[task]['properties']}
    messages = {'collect_brief': '想举办一场 100 人左右的 AI 交流会，预算 1200 元。还需要确定什么？',
                'generate_plan': '增加互动讨论，确保预算和结束时间不超出限制。',
                'generate_publicity': '面向零基础同学，文案亲切具体。', 'generate_recap': '客观总结实际数据，不夸大效果。',
                'answer_question': '', 'analyze_registration': '', 'analyze_onsite': '嘉宾预计晚到 20 分钟，请提出安排建议。', 'generate_review': ''}
    return {'input': data, 'message': messages[task]}


def validate_input(role, task, data):
    json.dumps(data, allow_nan=False)
    if task not in TASKS.get(role, {}):
        raise ValueError('该任务不属于当前 Agent')
    errors = list(Draft202012Validator(INPUTS[task]).iter_errors(data))
    if errors:
        error = errors[0]
        path = '.'.join(str(p) for p in error.path) or '$'
        raise ValueError(f'测试输入字段 {path} 不符合 {error.validator} 约束')
    brief = data['brief']
    if 'date' in brief:
        try:
            dt = datetime.fromisoformat(brief['date'])
            if dt.tzinfo is not None:
                raise ValueError()
        except ValueError:
            raise ValueError('测试活动时间必须为有效的本地 ISO 日期时间')
    if 'plan' in data:
        from .contracts import validate_plan
        clean = copy.deepcopy(data['plan'])
        for item in clean['timeline']:
            item.pop('id')
        validate_plan(clean, brief)
        ids = [t['id'] for t in data['plan']['timeline']]
        if len(ids) != len(set(ids)):
            raise ValueError('时间线环节 ID 不能重复')
    participants = data.get('participants', [])
    if len(participants) > brief.get('capacity', 100000):
        raise ValueError('样例报名人数不能超过容量')
    seen = set()
    for f in data.get('feedback', []):
        i = int(f['participant_index'])
        if i >= len(participants) or not participants[i]['checked_in']:
            raise ValueError('反馈必须引用已签到的样例参与者')
        key = (i, f['phase'])
        if key in seen:
            raise ValueError('同一参与者在同一阶段只能有一条反馈')
        seen.add(key)
