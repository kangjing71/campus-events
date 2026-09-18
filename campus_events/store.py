"""SQLite storage for campus events."""
import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get('EVENT_DB', str(ROOT / 'events.sqlite3')))
LOCK = threading.RLock()


class Problem(Exception):
    pass


def now():
    return datetime.now().isoformat(timespec='seconds')


def init_db():
    with sqlite3.connect(DB) as c:
        c.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS agent_runs (id TEXT PRIMARY KEY, event_id TEXT, data TEXT NOT NULL)')
        c.execute('INSERT OR IGNORE INTO config VALUES (?, ?)', ('admin_token', secrets.token_urlsafe(32)))


def admin_token():
    with sqlite3.connect(DB) as c:
        return c.execute("SELECT value FROM config WHERE key='admin_token'").fetchone()[0]


def load(eid):
    with sqlite3.connect(DB) as c:
        row = c.execute('SELECT data FROM events WHERE id=?', (eid,)).fetchone()
    if not row:
        raise Problem('活动不存在')
    return json.loads(row[0])


def save(e):
    e['updated_at'] = now()
    e['version'] = e.get('version', 0) + 1
    with sqlite3.connect(DB) as c:
        c.execute('INSERT OR REPLACE INTO events VALUES (?, ?)', (e['id'], json.dumps(e, ensure_ascii=False)))
