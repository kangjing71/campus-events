"""workspace 文件/终端工具的沙箱行为单测。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agents import workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        patcher = patch.object(workspace, 'ROOT', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.folder.cleanup)
        self.tools = workspace.workspace_tools('event-1')
        self.ws = self.root / 'workspaces' / 'event-1'

    def call(self, name, args):
        return self.tools[name]['handler'](args)

    def test_write_read_list_roundtrip(self):
        result = self.call('write_file', {'path': 'notes/plan.md', 'content': '# 方案'})
        self.assertTrue(result['ok'])
        self.assertEqual((self.ws / 'notes' / 'plan.md').read_text(encoding='utf-8'), '# 方案')
        self.assertEqual(self.call('read_file', {'path': 'notes/plan.md'})['content'], '# 方案')
        listing = self.call('list_files', {'path': '.'})
        self.assertEqual(listing['files'], ['notes/plan.md'])

    def test_path_escape_rejected(self):
        (self.root / 'secret.txt').write_text('secret', encoding='utf-8')
        for path in ('../secret.txt', '/etc/passwd', 'notes/../../secret.txt'):
            result = self.call('read_file', {'path': path})
            self.assertFalse(result['ok'], path)
            self.assertIn('workspace', result['error'])
        self.assertFalse(self.call('write_file', {'path': '../x.md', 'content': 'x'})['ok'])

    def test_read_missing_and_empty_write(self):
        self.assertFalse(self.call('read_file', {'path': 'none.md'})['ok'])
        self.assertFalse(self.call('write_file', {'path': 'a.md', 'content': '  '})['ok'])

    def test_run_command_in_workspace(self):
        result = self.call('run_command', {'command': 'echo hello > out.txt'})
        self.assertTrue(result['ok'])
        self.assertEqual((self.ws / 'out.txt').read_text().strip(), 'hello')

    def test_run_command_rejects_escape_and_substitution(self):
        for command in ('cat ../secret', 'cat /etc/passwd', 'echo $(whoami)', 'echo `whoami`', 'cat ~/x'):
            result = self.call('run_command', {'command': command})
            self.assertFalse(result['ok'], command)

    def test_run_command_nonzero_exit(self):
        result = self.call('run_command', {'command': 'exit 3'})
        self.assertFalse(result['ok'])
        self.assertEqual(result['exit_code'], 3)

    def test_invalid_event_id_rejected(self):
        with self.assertRaises(ValueError):
            workspace.workspace_dir('../evil')


if __name__ == '__main__':
    unittest.main()
