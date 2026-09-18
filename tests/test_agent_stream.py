"""stream_call 与 Agent 的流式行为单测：本地微型 SSE HTTP 服务，不依赖真实模型。"""
import copy
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
import server as s
from agents import runtime
from agents.agent import Agent, AgentError

RESULT = {'brief_patch': {'objective': '促进跨学院交流'}, 'reply': '已提取需求，请核对活动信息。', 'questions': ['请补充时间地点。']}
CONTENT = json.dumps(RESULT, ensure_ascii=False)


class StreamHandler(BaseHTTPRequestHandler):
    calls = []
    scenario = 'ok'

    def log_message(self, *args):
        pass

    def _json(self, code, value):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _sse(self, chunks):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(b'data: ' + json.dumps(chunk, ensure_ascii=False).encode() + b'\n\n')
            self.wfile.flush()

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        StreamHandler.calls.append(data)
        scenario = StreamHandler.scenario
        if scenario == 'unauthorized':
            return self._json(401, {'error': 'DO_NOT_EXPOSE_SECRET'})
        if scenario == 'nonstream':
            return self._json(200, {'choices': [{'message': {'role': 'assistant', 'content': CONTENT}}]})
        if scenario == 'truncated':
            self._sse([{'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': CONTENT[:10]}}]}])
            self.close_connection = True
            return
        if scenario == 'tool' and not any(m.get('role') == 'tool' for m in data.get('messages', [])):
            return self._json(200, {'choices': [{'message': {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': 'read-1', 'type': 'function', 'function': {'name': 'get_event_brief', 'arguments': '{}'}}]}}]})
        third = max(1, len(CONTENT) // 3)
        chunks = [{'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': CONTENT[i:i + third]}}]}
                  for i in range(0, len(CONTENT), third)]
        chunks[-1]['choices'][0]['finish_reason'] = 'stop'
        self._sse(chunks)


class StreamCallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = ThreadingHTTPServer(('127.0.0.1', 0), StreamHandler)
        cls.thread = threading.Thread(target=cls.service.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.service.shutdown()
        cls.service.server_close()
        cls.thread.join()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name)
        config = copy.deepcopy(runtime.DEFAULT_CONFIG)
        config['defaults']['protocol'] = 'chat_completions'
        for role, cfg in config['agents'].items():
            cfg.update(api_url=f'http://127.0.0.1:{self.service.server_port}/{role}', model='test-' + role,
                       prompt_file=str(s.ROOT / cfg['prompt_file']))
        self.config_path = self.path / 'agents.json'
        self.config_path.write_text(json.dumps(config), encoding='utf-8')
        env = {'AGENT_CONFIG': str(self.config_path), 'AGENT_ENV_FILE': str(self.path / '.env'),
               **{role.upper() + '_API_KEY': 'secret-' + role for role in runtime.ROLES}}
        self.env = patch.dict(os.environ, env, clear=True)
        self.env.start()
        StreamHandler.calls = []
        StreamHandler.scenario = 'ok'
        self.audit = []

    def tearDown(self):
        self.env.stop()
        self.folder.cleanup()

    def events_for(self, **kwargs):
        return list(runtime.stream_call('planning', 'collect_brief', {'message': '办一场活动'}, audit=self.audit.append, **kwargs))

    def test_deltas_in_order_and_result_validated(self):
        events = self.events_for()
        deltas = [event for event in events if event['type'] == 'delta']
        self.assertGreaterEqual(len(deltas), 2)
        self.assertEqual(events[0]['type'], 'delta')
        self.assertEqual(''.join(delta['text'] for delta in deltas), CONTENT)
        self.assertEqual(events[-1], {'type': 'result', 'value': RESULT})
        self.assertEqual(self.audit[-1]['status'], 'success')
        self.assertEqual(self.audit[-1]['attempts'], 1)
        self.assertTrue(all(call.get('stream') for call in StreamHandler.calls))

    def test_check_failure_triggers_streamed_repair(self):
        seen = []
        def check(value):
            seen.append(value)
            if len(seen) == 1:
                raise ValueError('业务校验不过')
        events = self.events_for(check=check)
        self.assertEqual(events[-1]['type'], 'result')
        self.assertEqual(len(StreamHandler.calls), 2)
        self.assertEqual(len(seen), 2)
        self.assertEqual(self.audit[-1]['attempts'], 2)

    def test_http_401_emits_error_event_without_secret(self):
        StreamHandler.scenario = 'unauthorized'
        events = self.events_for()
        self.assertEqual(events[-1]['type'], 'error')
        self.assertIn('HTTP 401', events[-1]['message'])
        self.assertNotIn('DO_NOT_EXPOSE_SECRET', json.dumps(events, ensure_ascii=False))
        self.assertEqual(self.audit[-1]['status'], 'error')
        self.assertEqual(len(StreamHandler.calls), 1)

    def test_truncated_stream_emits_error_event(self):
        StreamHandler.scenario = 'truncated'
        events = self.events_for()
        self.assertEqual(events[-1]['type'], 'error')
        self.assertIn('校验失败', events[-1]['message'])
        self.assertEqual(self.audit[-1]['status'], 'error')

    def test_non_sse_response_falls_back_to_plain_json(self):
        StreamHandler.scenario = 'nonstream'
        events = self.events_for()
        self.assertEqual(events[-1], {'type': 'result', 'value': RESULT})
        self.assertEqual([event for event in events if event['type'] == 'delta'], [])

    def test_tool_call_round_executes_snapshot_and_continues(self):
        StreamHandler.scenario = 'tool'
        tools = {'get_event_brief': {'description': '读取当前活动需求', 'data': {'name': '活动'}}}
        events = self.events_for(tools=tools)
        tool_events = [event for event in events if event['type'] == 'tool']
        self.assertEqual([event['name'] for event in tool_events], ['get_event_brief'])
        self.assertEqual(events[-1]['type'], 'result')
        second = StreamHandler.calls[-1]
        tool_messages = [m for m in second['messages'] if m['role'] == 'tool']
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(json.loads(tool_messages[0]['content']), {'name': '活动'})

    def test_tool_handler_result_sent_to_model(self):
        StreamHandler.scenario = 'tool'
        tools = {'get_event_brief': {'description': '生成方案', 'data': None, 'handler': lambda: {'generated': True}}}
        events = self.events_for(tools=tools)
        self.assertEqual(events[-1]['type'], 'result')
        tool_messages = [m for m in StreamHandler.calls[-1]['messages'] if m['role'] == 'tool']
        self.assertEqual(json.loads(tool_messages[0]['content']), {'generated': True})

    def test_agent_run_returns_value(self):
        self.assertEqual(Agent('planning').run('collect_brief', {'message': '办活动'}), RESULT)

    def test_agent_stream_yields_deltas_then_result(self):
        events = list(Agent('planning').stream('collect_brief', {'message': '办活动'}))
        self.assertEqual(events[0]['type'], 'delta')
        self.assertEqual(events[-1]['type'], 'result')

    def test_agent_run_raises_agent_error(self):
        StreamHandler.scenario = 'unauthorized'
        with self.assertRaises(AgentError):
            Agent('planning').run('collect_brief', {'message': '办活动'})


if __name__ == '__main__':
    unittest.main()
