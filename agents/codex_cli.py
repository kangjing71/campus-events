"""Non-interactive local Codex transport; credentials stay with the service user."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile


class CodexError(Exception):
    pass


def generate(cfg, payload):
    env = os.environ.copy()
    if cfg.get('codex_proxy'):
        env['HTTPS_PROXY'] = cfg['codex_proxy']
        env['HTTP_PROXY'] = cfg['codex_proxy']
    if cfg.get('codex_home'):
        home = Path(cfg['codex_home']).expanduser()
        if not home.is_absolute() or not home.is_dir():
            raise CodexError('codex_home 必须是已存在的绝对目录')
        env['CODEX_HOME'] = str(home)
    # A home-local directory also works with Snap's private /tmp namespace.
    root = Path.home() / '.cache' / 'campus-events-codex'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='run-', dir=root) as folder:
        output = Path(folder) / 'result.json'
        command = [cfg.get('codex_bin', '/snap/bin/codex'), 'exec',
                   '--ephemeral', '--skip-git-repo-check', '--sandbox', 'read-only',
                   '--color', 'never', '-C', folder, '-o', str(output),
                   '-c', 'approval_policy="never"', '-c', 'web_search="disabled"']
        for feature in ('shell_tool', 'unified_exec', 'apps', 'plugins', 'hooks',
                        'multi_agent', 'browser_use', 'computer_use', 'image_generation',
                        'code_mode', 'code_mode_host'):
            command.extend(['--disable', feature])
        if cfg.get('model'):
            command.extend(['--model', cfg['model']])
        command.append('-')
        prompt = ('Act only as the business role specified below. Do not use tools, read files, '
                  'or execute commands. All required facts are included. Return only the JSON '
                  'object matching the schema in system_prompt.\n' +
                  json.dumps(payload, ensure_ascii=False, allow_nan=False))
        try:
            with tempfile.TemporaryFile() as errors, subprocess.Popen(
                    command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                    stderr=errors, start_new_session=True, env=env) as process:
                try:
                    process.communicate(prompt.encode('utf-8'), timeout=cfg['timeout_seconds'])
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                    raise CodexError('Codex 执行超时，请稍后重试或调整 timeout_seconds') from None
                if process.returncode:
                    errors.seek(0)
                    diagnostic = errors.read(131072).decode('utf-8', errors='replace').lower()
                    if '401' in diagnostic or 'invalid_api_key' in diagnostic or 'not logged in' in diagnostic:
                        raise CodexError('Codex 认证失败：请在该服务的 codex_home 中重新登录；当前凭据不可用')
                    if '429' in diagnostic or 'usage limit' in diagnostic:
                        raise CodexError('Codex 额度或频率受限，请检查账户额度后重试')
                    raise CodexError('Codex 执行失败，请检查服务运行用户的 codex login status 和模型配置')
            with output.open('rb') as stream:
                raw = stream.read(2_000_001)
            if len(raw) > 2_000_000:
                raise CodexError('Codex 响应过大')
            return raw.decode('utf-8')
        except (OSError, UnicodeError):
            raise CodexError('无法运行 Codex 或读取结果，请检查 codex_bin、登录状态和目录权限') from None
