"""Campus event MVP. Python 3.10+, standard library only.

Thin facade over the campus_events package. All public names from the
original monolithic server.py are re-exported here; reads are forwarded
to the defining module, and assignments to storage-level names (DB, ROOT,
LOCK) are forwarded to campus_events.store so the dynamic database state
stays consistent.
"""
import sys
from types import ModuleType

from campus_events import domain, store, web

_STORE_NAMES = {'ROOT', 'DB', 'LOCK', 'sqlite3', 'init_db', 'admin_token', 'load', 'save', 'now', 'Problem'}
_DOMAIN_NAMES = {'FIELDS', 'REQUIRED', 'STATES', 'text', 'number', 'invoke', 'tool', 'feedback_evidence',
                 'registration_context', 'PlanningAgent', 'RegistrationAgent', 'PublicityAgent',
                 'OnsiteAgent', 'ReviewAgent', 'metrics', 'Orchestrator', 'new_event',
                 'public_event'}
_WEB_NAMES = {'Handler', 'main'}

class _ServerModule(ModuleType):
    def __setattr__(self, name, value):
        if name in ('DB', 'ROOT', 'LOCK'):
            setattr(store, name, value)
        else:
            super().__setattr__(name, value)


sys.modules[__name__].__class__ = _ServerModule


def __getattr__(name):
    if name in _STORE_NAMES:
        return getattr(store, name)
    if name in _DOMAIN_NAMES:
        return getattr(domain, name)
    if name in _WEB_NAMES:
        return getattr(web, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == '__main__':
    web.main()
