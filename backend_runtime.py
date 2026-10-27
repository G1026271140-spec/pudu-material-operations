"""Framework-independent configuration, cache and request-local utilities.

Authentication and authorization belong to FastAPI, never to this state map.
The realtime VM mode bypasses data caches, not durable queues or idempotency.
"""
from __future__ import annotations

import copy
import functools
import inspect
import os
import pickle
import threading
import time
import tomllib
from collections.abc import MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def secrets_path(root: Path | None = None) -> Path:
    return Path(os.environ.get('PUDU_SECRETS_FILE') or (root or ROOT) / 'config/secrets.toml')


def read_secrets(root: Path | None = None) -> dict:
    path = secrets_path(root)
    try:
        return tomllib.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return {}


def secret(name: str, default: str = '', *, root: Path | None = None) -> str:
    # Explicit process configuration wins. Malformed TOML is not silently ignored.
    if name in os.environ:
        return os.environ[name].strip()
    value = read_secrets(root).get(name)
    return str(default if value in (None, '') else value).strip()


class _State(MutableMapping):
    def __init__(self, name):
        object.__setattr__(self, '_value', ContextVar(name, default=None))

    def _mapping(self):
        value = self._value.get()
        if value is None:
            value = {}
            self._value.set(value)
        return value

    def __getitem__(self, key): return self._mapping()[key]
    def __setitem__(self, key, value): self._mapping()[key] = value
    def __delitem__(self, key): del self._mapping()[key]
    def __iter__(self): return iter(self._mapping())
    def __len__(self): return len(self._mapping())
    def __getattr__(self, name):
        try: return self[name]
        except KeyError as exc: raise AttributeError(name) from exc
    def __setattr__(self, name, value): self[name] = value


request_state = _State('pudu_request_state')
request_query = _State('pudu_request_query')
_scope_active = ContextVar('pudu_scope_active', default=False)


def in_request_scope() -> bool:
    return _scope_active.get()


def web_read_only() -> bool:
    return os.environ.get('PUDU_WEB_READ_ONLY', '').lower() in {'1', 'true', 'yes'}


@contextmanager
def request_scope(query=None):
    active_token = _scope_active.set(True)
    state_token = request_state._value.set({})
    query_token = request_query._value.set(dict(query or {}))
    try:
        yield
    finally:
        request_state._value.reset(state_token)
        request_query._value.reset(query_token)
        _scope_active.reset(active_token)


def realtime_reads() -> bool:
    return database_reads() or os.environ.get('PUDU_REALTIME_READS', '').lower() in {'1', 'true', 'yes'}


def database_reads() -> bool:
    return os.environ.get('PUDU_DATA_SOURCE', '').lower() == 'postgresql'


def database_editor_enabled() -> bool:
    return database_reads() and os.environ.get('PUDU_DB_EDITOR_ENABLED', '').lower() in {'1','true','yes'}


def database_business_writes_enabled() -> bool:
    return database_reads() and os.environ.get('PUDU_BUSINESS_WRITES_ENABLED','').lower() in {'1','true','yes'}


def database_worker_enabled() -> bool:
    return database_reads() and os.environ.get('PUDU_OUTBOX_WORKER_ENABLED','').lower() in {'1','true','yes'}


def release_database_snapshot():
    source=request_state.get('_live_reader')
    if source is not None and hasattr(source,'close'):
        source.close()
        del request_state['_live_reader']


class _Cache:
    def __init__(self, *, resource=False):
        self.resource = resource
        self._wrappers = []
        self._registry_lock = threading.RLock()

    def clear(self):
        with self._registry_lock:
            wrappers = list(self._wrappers)
        for function in wrappers:
            function.clear()

    def __call__(self, function=None, *, ttl=None, **_unused):
        if function is None:
            return lambda f: self(f, ttl=ttl)
        values = {}
        lock = threading.RLock()
        signature = inspect.signature(function)

        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            if not self.resource and realtime_reads():
                return function(*args, **kwargs)
            try:
                bound = signature.bind(*args, **kwargs)
                bound.apply_defaults()
                key = pickle.dumps({k: v for k, v in bound.arguments.items() if not k.startswith('_')})
            except (TypeError, pickle.PickleError, AttributeError):
                return function(*args, **kwargs)
            with lock:
                now = time.monotonic()
                found = values.get(key)
                if found is not None and (ttl is None or now - found[0] < float(ttl)):
                    return found[1] if self.resource else copy.deepcopy(found[1])
                value = function(*args, **kwargs)
                # Bound memory; errors are never cached.
                if len(values) >= 128:
                    values.pop(next(iter(values)))
                values[key] = (time.monotonic(), value if self.resource else copy.deepcopy(value))
                return value

        def clear(*_args, **_kwargs):
            with lock:
                values.clear()
        wrapped.clear = clear
        with self._registry_lock:
            self._wrappers.append(wrapped)
        return wrapped


cache_data = _Cache()
cache_resource = _Cache(resource=True)
