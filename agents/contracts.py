"""JSON contracts are appended to prompts and enforced before saving output."""
from datetime import datetime, timedelta
import math
from jsonschema import Draft202012Validator


def string(limit=10000, empty=False):
    return {'type': 'string', 'minLength': 0 if empty else 1, 'maxLength': limit}


def array(item, minimum=0, maximum=100):
    return {'type': 'array', 'items': item, 'minItems': minimum, 'maxItems': maximum}


def obj(properties, required=None):
    return {'type': 'object', 'properties': properties, 'required': list(properties) if required is None else required, 'additionalProperties': False}


def numeric(low, high, integer=False):
    return {'type': 'integer' if integer else 'number', 'minimum': low, 'maximum': high}


BRIEF_FIELDS = {
    **{k: string(500) for k in ['name', 'objective', 'type', 'level', 'format', 'date', 'location', 'audience', 'organizer', 'owner']},
    'capacity': numeric(1, 100000, True), 'budget': numeric(0, 10000000),
    'duration': numeric(30, 720, True), 'constraints': string(2000, empty=True)}
TARGETS = obj({'registration': numeric(1, 100000, True), 'attendance': numeric(1, 100000, True),
               'attendance_rate': numeric(0, 100), 'feedback': numeric(1, 100000, True), 'satisfaction': numeric(1, 5)})
PLAN = obj({
    'summary': string(30000),
    'timeline': array(obj({'time': string(30), 'title': string(200), 'owner': string(100)}), 2, 40),
    'preparation': array(obj({'day': string(100), 'task': string(1000)}), 1, 40),
    'roles': array(obj({'role': string(100), 'task': string(1000)}), 1, 30),
    'budget': array(obj({'item': string(200), 'amount': numeric(0, 10000000)}), 1, 50),
    'materials': array(string(500), 1, 50), 'risks': array(string(2000), 1, 30), 'targets': TARGETS})
SCHEMAS = {
    'collect_brief': obj({'brief_patch': obj(BRIEF_FIELDS, []), 'reply': string(5000), 'questions': array(string(1000), 0, 15)}),
    'generate_plan': PLAN,
    'generate_publicity': obj({'article': string(30000), 'group': string(10000), 'schedule': array(string(1000), 1, 20)}),
    'generate_recap': obj({'article': string(30000), 'group': string(10000), 'schedule': array(string(1000), 1, 20)}),
    'answer_question': obj({'answer': string(5000, empty=True), 'needs_human': {'type': 'boolean'}, 'reason': string(2000), 'evidence': array(string(1000), 0, 20)}),
    'analyze_registration': obj({'summary': string(10000), 'suggestions': array(string(2000), 1, 20), 'needs_attention': array(string(1000), 0, 30)}),
    'analyze_onsite': obj({'summary': string(10000), 'issues': array(obj({'topic': string(300), 'evidence_ids': array(string(100), 0, 100), 'suggestion': string(2000)}), 0, 30),
                           'adjustment': {'anyOf': [{'type': 'null'}, obj({'item_id': string(100), 'minutes': numeric(1, 180, True), 'reason': string(1000)})]}}),
    'generate_review': obj({'summary': string(30000), 'suggestions': array(string(3000), 1, 30),
                            'findings': array(obj({'observation': string(3000), 'evidence_ids': array(string(100), 1, 100), 'hypothesis': string(3000, empty=True)}), 0, 30)}),
    'connection_test': obj({'ok': {'const': True}}),
}


def validate(task, result):
    errors = sorted(Draft202012Validator(SCHEMAS[task]).iter_errors(result), key=lambda e: str(list(e.path)))
    if errors:
        first = errors[0]
        path = '.'.join(str(p) for p in first.path) or '$'
        raise ValueError(f'输出字段 {path} 不符合 {first.validator} 约束')


def validate_plan(plan, brief):
    validate('generate_plan', plan)
    start = datetime.fromisoformat(brief['date'])
    finish = start + timedelta(minutes=brief['duration'])
    times = []
    for item in plan['timeline']:
        try:
            time = datetime.fromisoformat(item['time'])
            if time.tzinfo is not None or not start - timedelta(hours=24) <= time <= finish:
                raise ValueError()
            times.append(time)
        except (TypeError, ValueError):
            raise ValueError('时间线必须使用本地 ISO 时间，且不得超出活动结束时间')
    if times != sorted(set(times)) or not any(t >= start for t in times) or times[-1] != finish:
        raise ValueError('时间线必须严格递增，并包含活动环节和准确结束时间')
    amounts = [x['amount'] for x in plan['budget']]
    if any(not math.isfinite(x) or abs(round(x * 100) - x * 100) > .0001 for x in amounts):
        raise ValueError('预算金额必须为有限数值，最多两位小数')
    if sum(round(x * 100) for x in amounts) > round(brief['budget'] * 100):
        raise ValueError('预算分项总额不能超过活动预算')
    t = plan['targets']
    if not t['feedback'] <= t['attendance'] <= t['registration'] <= brief['capacity']:
        raise ValueError('目标应满足反馈人数 ≤ 到场人数 ≤ 报名人数 ≤ 容量')
