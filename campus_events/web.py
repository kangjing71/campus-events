"""HTTP layer for campus events: request handler and server entry point."""
import argparse
import csv
import io
import json
import re
import secrets
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from agents import runtime
from . import store
from .store import ROOT, LOCK, init_db, admin_token, load, save
from .domain import (Problem, new_event, metrics, public_event,
                     PlanningAgent, RegistrationAgent, OnsiteAgent, Orchestrator)


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
                if path == '/api/events':
                    with store.sqlite3.connect(store.DB) as c:
                        events = [load(r[0]) for r in c.execute('SELECT id FROM events')]
                    return self.send(200, sorted([dict(e, metrics=metrics(e)) for e in events], key=lambda e: e['created_at'], reverse=True))
                match = re.fullmatch(r'/api/events/([\w-]+)(/export)?', path)
                if match:
                    e = load(match[1])
                    if match[2]:
                        stream = io.StringIO()
                        writer = csv.writer(stream)
                        q = e.get('questionnaire')
                        if q:
                            keys = [f['key'] for f in q['fields']]
                            writer.writerow([f['label'] for f in q['fields']] + ['报名时间', '签到时间'])
                            rows = [[r.get('answers', {}).get(k, '') for k in keys] + [r['at'], r.get('checked_at') or ''] for r in e['registrations']]
                        else:
                            keys = ['name', 'email', 'college', 'grade', 'needs']
                            writer.writerow(['姓名', '邮箱', '学院', '年级', '需求', '报名时间', '签到时间'])
                            rows = [[r.get(k) or '' for k in keys] + [r['at'], r.get('checked_at') or ''] for r in e['registrations']]
                        for vals in rows:
                            vals = [str(v) for v in vals]
                            writer.writerow(["'" + v if v.lstrip().startswith(('=', '+', '-', '@')) else v for v in vals])
                        return self.send(200, '\ufeff' + stream.getvalue(), 'text/csv; charset=utf-8')
                    return self.send(200, dict(e, metrics=metrics(e)))
                return self.send(404, {'error': '接口不存在'})
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
            stream = re.fullmatch(r'/api/events/([\w-]+)/chat_stream', path)
            if stream and not public:
                return self.chat_stream(stream[1], data)
            if public:
                eid, action = public.groups()
                live_id = version = None
                with LOCK:
                    e = load(eid)
                    if action == 'register':
                        result = RegistrationAgent.register(e, data)
                    elif action == 'checkin':
                        result = OnsiteAgent.checkin(e, data.get('ticket'))
                    elif action == 'feedback':
                        result = OnsiteAgent.feedback(e, data)
                        live_id = result.pop('live_id', None)
                    else:
                        r = next((r for r in e['registrations'] if r['id'] == data.get('ticket')), None)
                        if not r:
                            raise Problem('报名凭证无效')
                        return self.send(200, {'name': r['name'], 'checked_at': r['checked_at'], 'answer': r.get('answer'), 'question': r['question']})
                    save(e)
                    version = e.get('version')
                self.send(200, result)
                if live_id:
                    # 现场问题的建议生成（模型调用）放在响应之后、写锁之外
                    with LOCK:
                        e = load(eid)
                    OnsiteAgent.advise_live(e, live_id)
                    with LOCK:
                        if load(eid).get('version') == version:
                            save(e)
                return
            with LOCK:
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

    def chat_stream(self, eid, data):
        """策划对话流式端点：SSE 逐帧返回生成过程，结束后加锁比对版本再落库。"""
        self.protocol_version = 'HTTP/1.1'
        with LOCK:
            e = load(eid)
            if data.get('expected_version') != e.get('version'):
                return self.send(400, {'error': '活动数据已更新，请刷新并重新核对后操作'})
            if e['state'] not in Orchestrator.ALLOWED['planning_chat']:
                return self.send(400, {'error': '当前阶段不允许此操作，请刷新活动状态'})
            version = e.get('version')
        try:
            rules = runtime.settings('planning')['mode'] == 'rules'
        except runtime.AgentError:
            rules = False
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()

        def emit(event, payload):
            frame = f'event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'
            self.wfile.write(f'{len(frame.encode("utf-8")):X}\r\n{frame}\r\n'.encode('utf-8'))
            self.wfile.flush()

        generation = None
        failed = False
        try:
            if rules:
                PlanningAgent.collect(e, {'message': data.get('message')})
            else:
                generation = PlanningAgent.stream_collect(e, {'message': data.get('message')})
                for event in generation:
                    if event['type'] in ('delta', 'tool'):
                        emit(event['type'], event)
                    elif event['type'] == 'error':
                        failed = True
                        emit('error', {'message': event['message']})
                        break
            if not failed:
                last = e['planning_messages'][-1]
                emit('message', {'reply': last['content'], 'questions': last.get('questions', []),
                                 'missing_fields': last.get('missing_fields', [])})
                with LOCK:
                    if load(eid).get('version') != version:
                        failed = True
                        emit('error', {'message': '生成期间活动数据发生变化，本次结果未写入，请刷新后重试'})
                    else:
                        save(e)
                        emit('done', dict(e, metrics=metrics(e)))
            if failed:
                # 对话轮出错时，workspace 中已写入的方案文件仍同步保存，避免成果丢失
                PlanningAgent._sync_plan_file(e)
                if e.get('plan_md'):
                    with LOCK:
                        if load(eid).get('version') == version:
                            save(e)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (Problem, runtime.AgentError) as ex:
            failed = True
            try:
                emit('error', {'message': str(ex)})
            except OSError:
                pass
        except Exception:
            try:
                emit('error', {'message': '服务内部错误，本次操作未完成'})
            except OSError:
                pass
        finally:
            if generation is not None:
                generation.close()
            try:
                self.wfile.write(b'0\r\n\r\n')
                self.wfile.flush()
            except OSError:
                pass


def main():
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
        with store.sqlite3.connect(store.DB) as c:
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
