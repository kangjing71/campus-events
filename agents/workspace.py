"""Per-event workspace and sandboxed file/shell tools for agents.

每个活动对应 ROOT/workspaces/<event_id>/ 目录；所有工具操作都限制在该目录内，
错误以 dict 回执返回给模型，不向调用方抛异常。
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 256 * 1024
MAX_LIST = 200
CMD_TIMEOUT = 15
MAX_OUTPUT = 8000


def workspace_dir(event_id):
    if not re.fullmatch(r'[\w-]{1,64}', event_id or ''):
        raise ValueError('无效的活动 id')
    path = ROOT / 'workspaces' / event_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve(ws, path):
    if not isinstance(path, str) or not path.strip():
        raise ValueError('路径不能为空')
    target = (ws / path.strip()).resolve()
    if not target.is_relative_to(ws.resolve()):
        raise ValueError('路径超出 workspace 范围')
    return target


def _read_file(ws, args):
    try:
        target = _resolve(ws, args.get('path'))
        if not target.is_file():
            return {'ok': False, 'error': '文件不存在'}
        if target.stat().st_size > MAX_FILE_BYTES:
            return {'ok': False, 'error': '文件过大，无法读取'}
        return {'ok': True, 'path': str(target.relative_to(ws)), 'content': target.read_text(encoding='utf-8')}
    except (ValueError, OSError, UnicodeError) as ex:
        return {'ok': False, 'error': str(ex)}


def _write_file(ws, args):
    try:
        target = _resolve(ws, args.get('path'))
        content = args.get('content')
        if not isinstance(content, str) or not content.strip():
            return {'ok': False, 'error': '文件内容不能为空'}
        if len(content.encode('utf-8')) > MAX_FILE_BYTES:
            return {'ok': False, 'error': '文件内容过大'}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
        return {'ok': True, 'path': str(target.relative_to(ws)), 'bytes': len(content.encode('utf-8'))}
    except (ValueError, OSError) as ex:
        return {'ok': False, 'error': str(ex)}


def _list_files(ws, args):
    try:
        target = _resolve(ws, args.get('path') or '.')
        if not target.is_dir():
            return {'ok': False, 'error': '目录不存在'}
        files = sorted(str(p.relative_to(ws)) for p in target.rglob('*') if p.is_file())
        return {'ok': True, 'files': files[:MAX_LIST], 'truncated': len(files) > MAX_LIST}
    except (ValueError, OSError) as ex:
        return {'ok': False, 'error': str(ex)}


def _run_command(ws, args):
    command = args.get('command')
    if not isinstance(command, str) or not command.strip() or len(command) > 2000:
        return {'ok': False, 'error': '命令无效'}
    if '`' in command or '$(' in command:
        return {'ok': False, 'error': '命令包含不允许的替换语法'}
    for token in re.split(r'[\s;|&<>()]+', command):
        if not token:
            continue
        if token.startswith(('/', '~')) or '..' in token:
            return {'ok': False, 'error': f'命令包含 workspace 外的路径：{token[:50]}'}
    try:
        result = subprocess.run(['/bin/sh', '-c', command], cwd=ws, timeout=CMD_TIMEOUT,
                                env={'PATH': '/usr/local/bin:/usr/bin:/bin'}, capture_output=True, text=True)
        output = (result.stdout + result.stderr).strip()
        return {'ok': result.returncode == 0, 'exit_code': result.returncode,
                'output': output[:MAX_OUTPUT], 'truncated': len(output) > MAX_OUTPUT}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'error': f'命令执行超过 {CMD_TIMEOUT} 秒被终止'}
    except OSError as ex:
        return {'ok': False, 'error': str(ex)}


_PATH_PARAM = {'type': 'string', 'minLength': 1, 'maxLength': 200}


def workspace_tools(event_id):
    """返回绑定到指定活动 workspace 的文件/终端工具集。"""
    ws = workspace_dir(event_id)

    def wrap(fn):
        return lambda args: fn(ws, args)

    return {
        'list_files': {
            'description': '列出 workspace 中的文件（相对路径）',
            'parameters': {'type': 'object', 'properties': {'path': _PATH_PARAM}, 'additionalProperties': False},
            'handler': wrap(_list_files)},
        'read_file': {
            'description': '读取 workspace 中指定文件的内容',
            'parameters': {'type': 'object', 'properties': {'path': _PATH_PARAM}, 'required': ['path'], 'additionalProperties': False},
            'handler': wrap(_read_file)},
        'write_file': {
            'description': '在 workspace 中创建或覆盖指定文件（自动创建父目录）',
            'parameters': {'type': 'object', 'properties': {'path': _PATH_PARAM,
                           'content': {'type': 'string', 'minLength': 1, 'maxLength': MAX_FILE_BYTES}},
                           'required': ['path', 'content'], 'additionalProperties': False},
            'handler': wrap(_write_file)},
        'run_command': {
            'description': '在 workspace 内执行受限 shell 命令（禁止绝对路径、..、命令替换，15 秒超时）',
            'parameters': {'type': 'object', 'properties': {'command': {'type': 'string', 'minLength': 1, 'maxLength': 2000}},
                           'required': ['command'], 'additionalProperties': False},
            'handler': wrap(_run_command)},
    }
