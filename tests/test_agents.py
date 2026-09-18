import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
import server as s
from agents import runtime
from mock_provider import Provider, BRIEF, ThreadingHTTPServer


class AgentIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        cls.provider_thread = threading.Thread(target=cls.provider.serve_forever, daemon=True)
        cls.provider_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.provider.shutdown()
        cls.provider.server_close()
        cls.provider_thread.join()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name)
        config = copy.deepcopy(runtime.DEFAULT_CONFIG)
        config['defaults']['protocol'] = 'chat_completions'
        for role, cfg in config['agents'].items():
            cfg.update(api_url=f'http://127.0.0.1:{self.provider.server_port}/{role}', model='test-'+role,
                       prompt_file=str(s.ROOT / cfg['prompt_file']))
        self.config = config
        self.config_path = self.path / 'agents.json'
        self.write_config()
        env = {'AGENT_CONFIG': str(self.config_path), 'AGENT_ENV_FILE': str(self.path / '.env'),
               **{r.upper()+'_API_KEY': 'secret-'+r for r in runtime.ROLES}}
        self.env = patch.dict(os.environ, env, clear=True)
        self.env.start()
        self.old_db = s.DB
        s.DB = self.path / 'test.db'
        s.init_db()
        self.e = s.new_event('新活动')
        Provider.calls = []
        Provider.entered.clear()
        Provider.release.clear()

    def tearDown(self):
        Provider.release.set()
        s.DB = self.old_db
        self.env.stop()
        self.folder.cleanup()

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config), encoding='utf-8')

    def model(self, role, name):
        self.config['agents'][role]['model'] = name
        self.write_config()

    def open(self):
        s.Orchestrator.act(self.e, 'plan', BRIEF)
        s.Orchestrator.act(self.e, 'confirm_plan', {})
        s.Orchestrator.act(self.e, 'publicity', {})
        s.Orchestrator.act(self.e, 'confirm_publicity', {})

    def register(self):
        return s.RegistrationAgent.register(self.e, {'name': 'PRIVATE_NAME', 'email': 'private@example.com', 'college': '学院', 'question': '活动在哪里？'})['ticket']

    def test_all_five_roles_routed_with_distinct_credentials_and_tools(self):
        s.Orchestrator.act(self.e, 'planning_chat', {'message': '先讨论目标'})
        self.assertEqual(self.e['state'], 'DRAFT')
        self.assertEqual(self.e['planning_messages'][-1]['missing_fields'], [])
        s.Orchestrator.act(self.e, 'planning_chat', {'message': '补齐活动信息'})
        s.Orchestrator.act(self.e, 'plan_from_brief', {})
        self.assertIn('模型策划', self.e['plan']['summary'])
        s.Orchestrator.act(self.e, 'confirm_plan', {})
        s.Orchestrator.act(self.e, 'publicity', {})
        self.assertIn('模型群聊', self.e['publicity']['group'])
        s.Orchestrator.act(self.e, 'confirm_publicity', {})
        ticket = self.register()
        s.Orchestrator.act(self.e, 'answer_question', {'ticket': ticket})
        self.assertNotIn('answer', self.e['registrations'][0])
        draft = self.e['registrations'][0]['answer_draft']
        self.assertIn('大学报告厅', draft['answer'])
        s.Orchestrator.act(self.e, 'answer', {'ticket': ticket, 'answer': draft['answer']})
        s.Orchestrator.act(self.e, 'analyze_registration', {})
        s.Orchestrator.act(self.e, 'start', {})
        s.OnsiteAgent.checkin(self.e, ticket)
        s.OnsiteAgent.feedback(self.e, {'ticket': ticket, 'comment': '讨论太短', 'rating': 4})
        before = copy.deepcopy(self.e['plan']['timeline'])
        s.Orchestrator.act(self.e, 'analyze_onsite', {'message': '嘉宾晚到'})
        self.assertEqual(self.e['plan']['timeline'], before)
        self.assertEqual(self.e['pending_adjustment']['minutes'], 10)
        s.Orchestrator.act(self.e, 'approve_adjustment', {})
        s.Orchestrator.act(self.e, 'finish', {})
        s.Orchestrator.act(self.e, 'review', {})
        self.assertEqual(self.e['review']['metrics']['registration'], 1)
        self.assertEqual(self.e['review']['findings'][0]['evidence_ids'], ['metrics.registration'])
        s.Orchestrator.act(self.e, 'confirm_review', {})
        s.Orchestrator.act(self.e, 'confirm_recap', {})
        self.assertEqual(self.e['state'], 'COMPLETED')
        for role in runtime.ROLES:
            calls = [c for c in Provider.calls if c['path'] == '/'+role]
            self.assertTrue(calls, role)
            self.assertTrue(all(c['auth'] == 'Bearer secret-'+role for c in calls))
            self.assertTrue(any(r['role'] == role and r['tools'] for r in self.e['agent_runs']))
        for call in Provider.calls:
            serialized = json.dumps(call['context'])
            self.assertNotIn('private@example.com', serialized)
            self.assertNotIn('PRIVATE_NAME', serialized)
            self.assertNotIn(ticket, serialized)

    def test_custom_json_endpoint(self):
        self.config['agents']['registration']['protocol'] = 'json'
        self.write_config()
        self.open()
        s.Orchestrator.act(self.e, 'analyze_registration', {})
        self.assertIn('模型分析', self.e['registration_analysis']['summary'])
        request = Provider.calls[-1]['body']
        self.assertEqual(request['agent'], 'registration')
        self.assertIn('output_schema', request)

    def test_invalid_output_not_saved_and_no_rule_fallback(self):
        self.model('planning', 'invalid')
        with self.assertRaisesRegex(s.Problem, '校验失败'):
            s.PlanningAgent.generate(self.e, BRIEF)
        self.assertNotIn('plan', self.e)
        self.assertEqual(self.e['state'], 'DRAFT')
        self.assertEqual(self.e['agent_runs'][-1]['status'], 'error')

    def test_invalid_budget_and_fabricated_evidence_rejected(self):
        self.model('planning', 'over_budget')
        with self.assertRaisesRegex(s.Problem, '预算'):
            s.PlanningAgent.generate(self.e, BRIEF)
        self.model('planning', 'test-planning')
        self.open()
        s.Orchestrator.act(self.e, 'start', {})
        s.Orchestrator.act(self.e, 'finish', {})
        self.model('review', 'bad_evidence')
        with self.assertRaisesRegex(s.Problem, '证据'):
            s.Orchestrator.act(self.e, 'review', {})
        self.assertNotIn('review', self.e)

    def test_unauthorized_tools_rejected(self):
        self.model('planning', 'forbidden')
        with self.assertRaisesRegex(s.Problem, '未授权工具'):
            s.PlanningAgent.generate(self.e, BRIEF)
        self.assertEqual(self.e['state'], 'DRAFT')

    def test_repair_and_transient_retry(self):
        self.model('planning', 'repair')
        self.config['agents']['planning']['tool_calling'] = False
        self.write_config()
        s.PlanningAgent.generate(self.e, BRIEF)
        self.assertEqual(self.e['agent_runs'][-1]['attempts'], 2)
        self.model('publicity', 'transient')
        s.Orchestrator.act(self.e, 'confirm_plan', {})
        s.Orchestrator.act(self.e, 'publicity', {})
        self.assertTrue(self.e['publicity'])

    def test_auth_failure_is_sanitized_and_not_retried(self):
        self.model('planning', 'unauthorized')
        with self.assertRaisesRegex(s.Problem, 'HTTP 401') as caught:
            s.PlanningAgent.generate(self.e, BRIEF)
        self.assertNotIn('DO_NOT_EXPOSE_SECRET', str(caught.exception))
        self.assertEqual(len(Provider.calls), 1)
        self.assertNotIn('secret-planning', json.dumps(runtime.status()))
        self.assertNotIn('secret-planning', json.dumps(self.e['agent_runs']))

    def test_env_and_prompt_hot_reload(self):
        prompt = self.path / 'planning.md'
        prompt.write_text('自定义策划 prompt', encoding='utf-8')
        self.config['agents']['planning']['prompt_file'] = str(prompt)
        self.write_config()
        (self.path / '.env').write_text('PLANNING_MODEL=hot-reload\n', encoding='utf-8')
        s.PlanningAgent.generate(self.e, BRIEF)
        self.assertEqual(Provider.calls[0]['body']['model'], 'hot-reload')
        self.assertTrue(Provider.calls[0]['body']['messages'][0]['content'].startswith('自定义策划 prompt'))

    def test_slow_model_does_not_block_registration_or_overwrite_changes(self):
        self.open()
        s.save(self.e)
        self.model('registration', 'slow')
        app = ThreadingHTTPServer(('127.0.0.1', 0), s.Handler)
        worker = threading.Thread(target=app.serve_forever, daemon=True)
        worker.start()
        root = f'http://127.0.0.1:{app.server_port}'
        def post(path, data, auth=False):
            headers = {'Content-Type': 'application/json'}
            if auth:
                headers['Authorization'] = 'Bearer '+s.admin_token()
            req = urllib.request.Request(root+path, json.dumps(data).encode(), headers)
            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as ex:
                return ex.code, json.load(ex)
        result = []
        job = threading.Thread(target=lambda: result.append(post('/api/events/'+self.e['id']+'/actions/analyze_registration', {'expected_version': self.e['version']}, True)))
        try:
            job.start()
            self.assertTrue(Provider.entered.wait(3))
            code, _ = post('/api/public/'+self.e['id']+'/register', {'name': '同学', 'email': 'new@example.com', 'college': '学院'})
            self.assertEqual(code, 200)
            Provider.release.set()
            job.join(5)
            self.assertEqual(result[0][0], 409)
            self.assertEqual(len(s.load(self.e['id'])['registrations']), 1)
            self.assertNotIn('registration_analysis', s.load(self.e['id']))
        finally:
            Provider.release.set()
            job.join(5)
            app.shutdown()
            app.server_close()
            worker.join()


if __name__ == '__main__':
    unittest.main()
