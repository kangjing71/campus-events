"""Opt-in live verification: python3 verify_codex.py --live (uses account quota)."""
import argparse
import json
from pathlib import Path
import time
import urllib.request
import server
from agents import playground


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    parser.add_argument('--report', default='/tmp/campus-codex-live-report.json')
    args = parser.parse_args()
    headers = {'Authorization': 'Bearer ' + server.admin_token(), 'Content-Type': 'application/json'}

    def request(path, payload=None):
        body = None if payload is None else json.dumps(payload).encode()
        with urllib.request.urlopen(urllib.request.Request(args.url + path, body, headers), timeout=400) as response:
            return json.load(response)

    before = request('/api/events')
    settings = request('/api/agents')
    report = {'settings': settings, 'results': []}
    try:
        for role, tasks in playground.TASKS.items():
            started = time.monotonic()
            result = request('/api/agents/' + role + '/test', {})
            assert result.get('ok') is True, result
            report['results'].append({'role': role, 'task': 'connection_test', 'ok': True,
                                      'seconds': round(time.monotonic() - started, 2)})
            print(role, 'connection_test', 'PASS', flush=True)
            for task in tasks:
                result = request('/api/agents/' + role + '/playground', {'task': task, **playground.example(task)})
                assert result['run']['mode'] == 'model' and result['run']['status'] == 'success', result
                assert result['persisted_to_event'] is False, result
                report['results'].append({'role': role, 'task': task, 'ok': True, 'run': result['run'], 'result': result['result']})
                print(role, task, 'PASS', result['run']['duration_ms'], 'ms', flush=True)
        report['events_unchanged'] = request('/api/events') == before
        assert report['events_unchanged']
        report['ok'] = True
    finally:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Report:', args.report, flush=True)


if __name__ == '__main__':
    main()
