"""SQLite persistence helpers for the anonymous review issuer."""

from __future__ import annotations

import json
import os
import sqlite3

DB_PATH = os.environ.get("ISSUER_DB_PATH", "issuer.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = _connect()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                sid TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                ts REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS oauth_states (
                state TEXT PRIMARY KEY,
                ts REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS issued (
                pr_key TEXT NOT NULL,
                user_id TEXT NOT NULL,
                PRIMARY KEY (pr_key, user_id)
            )
        """)
    conn.close()


def get_session(sid: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT data FROM sessions WHERE sid = ?", (sid,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])
    finally:
        conn.close()


def set_session(sid: str, data: dict, ts: float) -> None:
    conn = _connect()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO sessions (sid, data, ts) VALUES (?, ?, ?)",
            (sid, json.dumps(data), ts),
        )
    conn.close()


def delete_session(sid: str) -> None:
    conn = _connect()
    with conn:
        conn.execute("DELETE FROM sessions WHERE sid = ?", (sid,))
    conn.close()


def add_oauth_state(state: str, ts: float) -> None:
    conn = _connect()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO oauth_states (state, ts) VALUES (?, ?)",
            (state, ts),
        )
    conn.close()


def pop_oauth_state(state: str) -> bool:
    """Check if the state exists, delete it, and return True/False."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM oauth_states WHERE state = ?", (state,)
        ).fetchone()
        if row is None:
            return False
        with conn:
            conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        return True
    finally:
        conn.close()


def is_issued(pr_key: str, user_id: str | int) -> bool:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM issued WHERE pr_key = ? AND user_id = ?",
            (pr_key, str(user_id)),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def mark_issued(pr_key: str, user_id: str | int) -> None:
    conn = _connect()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO issued (pr_key, user_id) VALUES (?, ?)",
            (pr_key, str(user_id)),
        )
    conn.close()
