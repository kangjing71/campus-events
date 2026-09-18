import copy
import tempfile
import unittest
from pathlib import Path
import sys
import os
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as s
from agents import runtime


BRIEF = {'name': '测试活动', 'objective': '交流学习', 'type': '分享', 'level': '校级', 'format': '线下',
         'date': '2026-10-10T19:00', 'location': '报告厅', 'audience': '全校学生', 'capacity': 2,
         'budget': 100, 'organizer': '社团', 'owner': '负责人', 'duration': 120}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.env = patch.dict(os.environ, {**{r.upper()+'_MODE': 'rules' for r in runtime.ROLES},
                                           'AGENT_ENV_FILE': str(Path(self.folder.name) / '.env')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.e = s.new_event('测试活动')

    def open(self):
        s.Orchestrator.act(self.e, 'plan', BRIEF)
        s.Orchestrator.act(self.e, 'confirm_plan', {})
        s.Orchestrator.act(self.e, 'publicity', {})
        s.Orchestrator.act(self.e, 'confirm_publicity', {})

    def register(self, email='student@example.com'):
        return s.RegistrationAgent.register(self.e, {'name': '同学', 'email': email, 'contact': email, 'college': '信息学院'})['ticket']

    def test_confirmation_gates(self):
        for action in ['confirm_plan', 'publicity', 'confirm_publicity', 'start', 'review', 'confirm_recap']:
            with self.assertRaises(s.Problem):
                s.Orchestrator.act(self.e, action, {})
        with self.assertRaises(s.Problem):
            self.register()

    def test_required_fields_and_numbers(self):
        for key in list(s.REQUIRED) + ['duration']:
            brief = BRIEF.copy()
            del brief[key]
            with self.assertRaises(s.Problem):
                s.PlanningAgent.generate(self.e, brief)
        for cap in ['nan', -1, 0, 1.5]:
            with self.assertRaises(s.Problem):
                s.PlanningAgent.generate(self.e, dict(BRIEF, capacity=cap))

    def test_optional_fields_may_be_omitted(self):
        brief = {k: v for k, v in BRIEF.items() if k not in ('objective', 'level', 'organizer', 'owner', 'constraints')}
        s.PlanningAgent.generate(self.e, brief)
        self.assertEqual(self.e['brief']['owner'], '活动负责人')
        self.assertEqual(self.e['state'], 'WAITING_PLAN_CONFIRMATION')

    def test_registration_cap_and_duplicates(self):
        self.open()
        self.register()
        with self.assertRaises(s.Problem):
            self.register('STUDENT@example.com')
        self.register('second@example.com')
        with self.assertRaises(s.Problem):
            self.register('third@example.com')
        self.assertEqual(len(self.e['registrations']), 2)

    def test_feedback_requires_attendance(self):
        self.open()
        token = self.register()
        s.Orchestrator.act(self.e, 'start', {})
        with self.assertRaises(s.Problem):
            s.OnsiteAgent.feedback(self.e, {'ticket': token, 'comment': '测试'})

    def test_checkin_idempotent_and_ticket_required(self):
        self.open()
        token = self.register()
        s.Orchestrator.act(self.e, 'start', {})
        with self.assertRaises(s.Problem):
            s.OnsiteAgent.checkin(self.e, 'invalid')
        first = s.OnsiteAgent.checkin(self.e, token)
        self.assertEqual(first, s.OnsiteAgent.checkin(self.e, token))
        self.assertEqual(s.metrics(self.e)['attendance'], 1)

    def test_feedback_deduplicated_and_post_rating_preferred(self):
        self.open()
        token = self.register()
        s.Orchestrator.act(self.e, 'start', {})
        s.OnsiteAgent.checkin(self.e, token)
        for rating in [3, 4]:
            s.OnsiteAgent.feedback(self.e, {'ticket': token, 'rating': rating, 'comment': '现场'})
        self.assertEqual(len(self.e['feedback_pool']), 1)
        s.Orchestrator.act(self.e, 'finish', {})
        s.OnsiteAgent.feedback(self.e, {'ticket': token, 'rating': 5, 'comment': '活动后'})
        m = s.metrics(self.e)
        self.assertEqual((m['feedback'], m['rating_count'], m['satisfaction']), (1, 1, 5))

    def test_adjustment_requires_approval_and_preserves_original(self):
        self.open()
        s.Orchestrator.act(self.e, 'start', {})
        before = copy.deepcopy(self.e['plan']['timeline'])
        s.Orchestrator.act(self.e, 'adjust', {'item_id': before[2]['id'], 'minutes': 10, 'reason': '嘉宾迟到'})
        self.assertEqual(self.e['plan']['timeline'], before)
        with self.assertRaises(s.Problem):
            s.Orchestrator.act(self.e, 'finish', {})
        s.Orchestrator.act(self.e, 'approve_adjustment', {})
        self.assertEqual(self.e['plan']['timeline'][:2], before[:2])
        self.assertNotEqual(self.e['plan']['timeline'][2], before[2])
        self.assertEqual(self.e['approved_plan']['timeline'], before)

    def test_empty_metrics_are_not_fabricated(self):
        self.open()
        s.Orchestrator.act(self.e, 'start', {})
        s.Orchestrator.act(self.e, 'finish', {})
        s.Orchestrator.act(self.e, 'review', {})
        self.assertIsNone(self.e['review']['metrics']['satisfaction'])
        self.assertIsNone(self.e['review']['metrics']['attendance_rate'])

    def test_full_lifecycle_and_report_freeze(self):
        self.open()
        token = self.register()
        s.Orchestrator.act(self.e, 'start', {})
        s.OnsiteAgent.checkin(self.e, token)
        s.Orchestrator.act(self.e, 'finish', {})
        s.OnsiteAgent.feedback(self.e, {'ticket': token, 'rating': 5, 'comment': '有收获'})
        s.Orchestrator.act(self.e, 'review', {})
        with self.assertRaises(s.Problem):
            s.OnsiteAgent.feedback(self.e, {'ticket': token, 'rating': 1, 'comment': '修改'})
        s.Orchestrator.act(self.e, 'confirm_review', {})
        self.assertEqual(self.e['state'], 'WAITING_RECAP_CONFIRMATION')
        s.Orchestrator.act(self.e, 'confirm_recap', {})
        self.assertEqual(self.e['state'], 'COMPLETED')
        self.assertEqual(self.e['review']['metrics']['satisfaction'], 5)

    def test_public_response_excludes_private_data(self):
        self.open()
        self.register()
        result = s.public_event(self.e)
        for key in ['registrations', 'logs', 'feedback_pool', 'owner', 'budget']:
            self.assertNotIn(key, result)
            self.assertNotIn(key, result['brief'])

    def test_sqlite_persistence(self):
        original = s.DB
        with tempfile.TemporaryDirectory() as folder:
            try:
                s.DB = Path(folder) / 'test.db'
                s.init_db()
                self.open()
                self.register()
                s.save(self.e)
                self.assertEqual(s.load(self.e['id']), self.e)
                first_key = s.admin_token()
                s.init_db()
                self.assertEqual(first_key, s.admin_token())
            finally:
                s.DB = original


if __name__ == '__main__':
    unittest.main()
