import unittest
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from agents.codex_cli import generate, CodexError


class CodexTransportTests(unittest.TestCase):
    def test_explicit_home_and_sanitized_auth_failure(self):
        process = MagicMock()
        process.__enter__.return_value = process
        process.returncode = 1
        with tempfile.TemporaryDirectory() as home:
            def launch(command, **kwargs):
                self.assertEqual(kwargs['env']['CODEX_HOME'], home)
                self.assertEqual(kwargs['env']['HTTPS_PROXY'], 'http://127.0.0.1:7897')
                kwargs['stderr'].write(b'401 invalid_api_key PRIVATE_TOKEN')
                return process
            with patch('agents.codex_cli.subprocess.Popen', side_effect=launch):
                with self.assertRaisesRegex(CodexError, '认证失败') as caught:
                    generate({'timeout_seconds': 2, 'codex_home': home, 'codex_proxy': 'http://127.0.0.1:7897'}, {})
                self.assertNotIn('PRIVATE_TOKEN', str(caught.exception))

    def test_stdin_isolated_directory_and_readonly(self):
        process = MagicMock()
        process.__enter__.return_value = process
        process.returncode = 0
        def launch(command, **kwargs):
            Path(command[command.index('-o') + 1]).write_text('{"ok":true}')
            self.assertEqual(command[-1], '-')
            self.assertIn('read-only', command)
            self.assertIn('--ephemeral', command)
            self.assertNotIn('shell', kwargs)
            self.assertTrue(kwargs['start_new_session'])
            return process
        with patch('agents.codex_cli.subprocess.Popen', side_effect=launch):
            self.assertEqual(generate({'timeout_seconds': 2}, {'context': 'private'}), '{"ok":true}')
        self.assertIn(b'private', process.communicate.call_args.args[0])

    def test_error_does_not_expose_provider_details(self):
        process = MagicMock()
        process.__enter__.return_value = process
        process.returncode = 1
        with patch('agents.codex_cli.subprocess.Popen', return_value=process):
            with self.assertRaises(CodexError):
                generate({'timeout_seconds': 2}, {})

    def test_timeout_kills_process_group(self):
        process = MagicMock()
        process.__enter__.return_value = process
        process.communicate.side_effect = [subprocess.TimeoutExpired('codex', 2), None]
        with patch('agents.codex_cli.subprocess.Popen', return_value=process), patch('agents.codex_cli.os.killpg') as kill:
            with self.assertRaisesRegex(CodexError, '超时'):
                generate({'timeout_seconds': 2}, {})
            kill.assert_called_once()
