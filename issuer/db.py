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
        # Short-lived server-side state for the browser-side proving flow. The
        # browser proves locally and posts the proof back, so anything the
        # backend must be able to trust (pseudonym, reputation chips, the
        # timestamp bound into the proof) is held here rather than round-tripped
        # through the client where it could be forged.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ephemeral (
                key TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                ts REAL NOT NULL
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


def put_ephemeral(key: str, data: dict, ts: float) -> None:
    conn = _connect()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO ephemeral (key, data, ts) VALUES (?, ?, ?)",
            (key, json.dumps(data), ts),
        )
    conn.close()


def get_ephemeral(key: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT data FROM ephemeral WHERE key = ?", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()


def pop_ephemeral(key: str) -> dict | None:
    """Single-use read. Used for the credential token so a proving session
    cannot be replayed."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT data FROM ephemeral WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        with conn:
            conn.execute("DELETE FROM ephemeral WHERE key = ?", (key,))
        return json.loads(row[0])
    finally:
        conn.close()


def prune_ephemeral(older_than_ts: float) -> None:
    conn = _connect()
    with conn:
        conn.execute("DELETE FROM ephemeral WHERE ts < ?", (older_than_ts,))
    conn.close()


def mark_issued(pr_key: str, user_id: str | int) -> None:
    conn = _connect()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO issued (pr_key, user_id) VALUES (?, ?)",
            (pr_key, str(user_id)),
        )
    conn.close()
