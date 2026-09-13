"""SQLite storage for settings, pairing codes and device sessions."""
import json
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager

from app import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def init() -> None:
    global _conn
    _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    with _lock, _conn:
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                device_id TEXT NOT NULL UNIQUE,
                device_name TEXT NOT NULL,
                created_at REAL NOT NULL,
                last_seen REAL NOT NULL
            );
            """
        )


def close() -> None:
    global _conn
    if _conn is not None:
        with _lock:
            _conn.close()
        _conn = None


@contextmanager
def _tx():
    with _lock:
        try:
            yield _conn
            _conn.commit()
        except Exception:
            _conn.rollback()
            raise


# ---------------------------------------------------------------- settings

def get_setting(key: str, default=None):
    with _lock:
        row = _conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return row["value"]


def set_setting(key: str, value) -> None:
    with _tx() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )


# ---------------------------------------------------------------- sessions

def create_session(device_name: str) -> dict:
    token = secrets.token_urlsafe(32)
    device_id = secrets.token_hex(8)
    now = time.time()
    with _tx() as conn:
        conn.execute(
            "INSERT INTO sessions (token, device_id, device_name, created_at, last_seen) "
            "VALUES (?, ?, ?, ?, ?)",
            (token, device_id, device_name, now, now),
        )
    return {"token": token, "device_id": device_id, "device_name": device_name}


def get_session(token: str) -> sqlite3.Row | None:
    if not token:
        return None
    with _lock:
        row = _conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
    if row is None:
        return None
    cutoff = time.time() - config.SESSION_TTL_DAYS * 86400
    if row["last_seen"] < cutoff:
        delete_session(token)
        return None
    return row


def touch_session(token: str) -> None:
    with _tx() as conn:
        conn.execute("UPDATE sessions SET last_seen = ? WHERE token = ?", (time.time(), token))


def list_sessions() -> list[dict]:
    with _lock:
        rows = _conn.execute(
            "SELECT device_id, device_name, created_at, last_seen FROM sessions ORDER BY last_seen DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_session(token: str) -> None:
    with _tx() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def delete_session_by_device(device_id: str) -> str | None:
    with _tx() as conn:
        row = conn.execute("SELECT token FROM sessions WHERE device_id = ?", (device_id,)).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM sessions WHERE device_id = ?", (device_id,))
    return row["token"]


def delete_all_sessions() -> list[str]:
    with _tx() as conn:
        rows = conn.execute("SELECT token FROM sessions").fetchall()
        conn.execute("DELETE FROM sessions")
    return [r["token"] for r in rows]
