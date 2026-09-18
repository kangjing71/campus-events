"""Local deterministic provider for integration tests; never used by production."""
import json
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BRIEF = {'name': '模型生成的校园交流会', 'objective': '促进跨学院交流', 'type': '交流', 'level': '校级', 'format': '线下',
         'date': '2026-10-10T19:00', 'location': '大学报告厅', 'audience': '全校学生', 'capacity': 100,
         'budget': 1200, 'organizer': '科技协会', 'owner': '负责人', 'duration': 120, 'constraints': '21:00 前结束'}


def output(task, context):
    if task == 'connection_test':
        return {'ok': True}
    if task == 'collect_brief':
        patch = {'objective': '促进跨学院交流'} if '先讨论' in context['message'] else BRIEF.copy()
        return {'brief_patch': patch, 'reply': '已提取需求，请核对活动信息。', 'questions': ['请补充时间地点。'] if len(patch) == 1 else []}
    if task == 'generate_plan':
        b = context['brief']
        start = datetime.fromisoformat(b['date'])
        return {'summary': '模型策划：加入跨学院讨论，按时结束。',
                'timeline': [{'time': (start + timedelta(minutes=n)).isoformat(timespec='minutes'), 'title': title, 'owner': b['owner']}
                             for n, title in [(0, '开场'), (10, '主题分享'), (b['duration'], '活动结束')]],
                'preparation': [{'day': 'T-7', 'task': '确认场地并宣传'}], 'roles': [{'role': '负责人', 'task': '协调现场'}],
                'budget': [{'item': '物资', 'amount': b['budget']}], 'materials': ['话筒'], 'risks': ['提前测试设备'],
                'targets': {'registration': b['capacity'], 'attendance': max(1, round(b['capacity']*.8)), 'feedback': max(1, round(b['capacity']*.5)), 'attendance_rate': 80, 'satisfaction': 4}}
    if task in ('generate_publicity', 'generate_recap'):
        b = context['brief']
        core = b['name']+' '+b['date']+' '+b['location']+' '+context['registration_path']
        return {'article': '模型公众号草稿：'+core, 'group': '模型群聊草稿：'+core, 'schedule': ['负责人确认后手动发布']}
    if task == 'answer_question':
        return {'answer': '活动地点：'+context['facts']['location'], 'needs_human': False, 'reason': '活动地点已有明确记录', 'evidence': [context['facts']['location']]}
    if task == 'analyze_registration':
        return {'summary': f"模型分析：已报名 {context['metrics']['registration']} 人。", 'suggestions': ['负责人在 T-3 核对报名进度。'], 'needs_attention': ['核对未答复问题']}
    if task == 'analyze_onsite':
        return {'summary': '模型现场分析：建议顺延分享环节。',
                'issues': [{'topic': '互动时间', 'evidence_ids': [context['feedback'][0]['id']], 'suggestion': '延长讨论'}] if context['feedback'] else [],
                'adjustment': {'item_id': context['timeline'][1]['id'], 'minutes': 10, 'reason': '工作人员提出嘉宾晚到'}}
    if task == 'generate_review':
        return {'summary': '模型复盘：以实际报名和签到数据评估活动。', 'suggestions': ['下次由现场组提前 30 分钟开放签到。'],
                'findings': [{'observation': f"实际报名 {context['metrics']['registration']} 人。", 'evidence_ids': ['metrics.registration'], 'hypothesis': '宣传覆盖可能不足，需进一步核实。'}]}
    raise ValueError(task)


class Provider(BaseHTTPRequestHandler):
    calls = []
    entered = threading.Event()
    release = threading.Event()

    def log_message(self, *args):
        pass

    def send(self, code, value):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        custom = 'messages' not in data
        payload = data if custom else json.loads(data['messages'][1]['content'])
        task, context = payload['task'], payload['context']
        mode = data.get('model', '')
        self.calls.append({'path': self.path, 'task': task, 'context': context, 'body': data, 'auth': self.headers.get('Authorization')})
        if mode == 'unauthorized':
            return self.send(401, {'error': 'DO_NOT_EXPOSE_SECRET'})
        if mode == 'transient' and len([c for c in self.calls if c['body'].get('model') == mode]) == 1:
            return self.send(429, {})
        if mode == 'slow':
            self.entered.set()
            self.release.wait(8)
        if not custom and data.get('tools') and not any(m['role'] == 'tool' for m in data['messages']):
            name = 'delete_everything' if mode == 'forbidden' else data['tools'][0]['function']['name']
            return self.send(200, {'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'read-1', 'type': 'function', 'function': {'name': name, 'arguments': '{}'}}]}}]})
        result = output(task, context)
        if mode == 'invalid' or (mode == 'repair' and len(data.get('messages', [])) < 3):
            result = {'wrong': 'shape'}
        if mode == 'bad_evidence' and task == 'generate_review':
            result['findings'][0]['evidence_ids'] = ['invented']
        if mode == 'over_budget' and task == 'generate_plan':
            result['budget'][0]['amount'] = context['brief']['budget'] + 1
        if custom:
            return self.send(200, result)
        content = json.dumps(result, ensure_ascii=False)
        if data.get('stream'):
            third = max(1, len(content) // 3)
            chunks = [{'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': content[i:i + third]}}]}
                      for i in range(0, len(content), third)]
            chunks[-1]['choices'][0]['finish_reason'] = 'stop'
            body = b''.join(b'data: ' + json.dumps(chunk, ensure_ascii=False).encode() + b'\n\n' for chunk in chunks) + b'data: [DONE]\n\n'
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            self.wfile.write(body)
            return
        return self.send(200, {'choices': [{'message': {'role': 'assistant', 'content': content}}]})


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--port', type=int, default=18766)
    args = p.parse_args()
    service = ThreadingHTTPServer(('127.0.0.1', args.port), Provider)
    print('Mock ready', flush=True)
    service.serve_forever()
