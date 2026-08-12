"""Persistence for the anonymous review issuer.

Runs on SQLite locally and Postgres when DATABASE_URL is set. See backend/db.py
for why: a serverless host has no durable filesystem, so SQLite would drop
sessions and issuance records on every cold start.

Kept as a separate module from the backend's rather than shared, because the two
deploy as independent units. That separation is deliberate: the issuer sees
reviewer identity and the backend sees proofs, and nothing should make it
convenient for one process to hold both.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator, Sequence

DB_PATH = os.environ.get("ISSUER_DB_PATH", "issuer.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
IS_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))

if IS_POSTGRES:  # pragma: no cover - exercised via DATABASE_URL
    import psycopg


def _sql(query: str) -> str:
    """SQLite's `?` placeholders to Postgres's `%s`."""
    return query.replace("?", "%s") if IS_POSTGRES else query


def _upsert(table: str, key: str, columns: tuple[str, ...]) -> str:
    """INSERT ... ON CONFLICT DO UPDATE, in whichever dialect is active."""
    cols = ", ".join(columns)
    marks = ", ".join("?" for _ in columns)
    if IS_POSTGRES:
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != key)
        return (
            f"INSERT INTO {table} ({cols}) VALUES ({marks}) "
            f"ON CONFLICT ({key}) DO UPDATE SET {updates}"
        )
    return f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({marks})"


def _insert_ignore(table: str, columns: tuple[str, ...]) -> str:
    cols = ", ".join(columns)
    marks = ", ".join("?" for _ in columns)
    if IS_POSTGRES:
        return f"INSERT INTO {table} ({cols}) VALUES ({marks}) ON CONFLICT DO NOTHING"
    return f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({marks})"


# Postgres has no REAL-with-sqlite-semantics; DOUBLE PRECISION is the portable
# choice for the unix timestamps stored here.
_TS_TYPE = "DOUBLE PRECISION" if IS_POSTGRES else "REAL"


@contextmanager
def _conn() -> Iterator[Any]:
    if IS_POSTGRES:
        conn = psycopg.connect(DATABASE_URL)
    else:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _fetchone(conn: Any, query: str, params: Sequence[Any]) -> tuple | None:
    cur = conn.cursor()
    cur.execute(_sql(query), tuple(params))
    return cur.fetchone()


def init_db() -> None:
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS sessions (
                sid TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                ts {_TS_TYPE} NOT NULL
            )
        """)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS oauth_states (
                state TEXT PRIMARY KEY,
                ts {_TS_TYPE} NOT NULL
            )
        """)
        cur.execute("""
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
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS ephemeral (
                key TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                ts {_TS_TYPE} NOT NULL
            )
        """)


def get_session(sid: str) -> dict | None:
    with _conn() as conn:
        row = _fetchone(conn, "SELECT data FROM sessions WHERE sid = ?", (sid,))
    return json.loads(row[0]) if row else None


def set_session(sid: str, data: dict, ts: float) -> None:
    with _conn() as conn:
        conn.cursor().execute(
            _sql(_upsert("sessions", "sid", ("sid", "data", "ts"))),
            (sid, json.dumps(data), ts),
        )


def delete_session(sid: str) -> None:
    with _conn() as conn:
        conn.cursor().execute(_sql("DELETE FROM sessions WHERE sid = ?"), (sid,))


def add_oauth_state(state: str, ts: float) -> None:
    with _conn() as conn:
        conn.cursor().execute(
            _sql(_upsert("oauth_states", "state", ("state", "ts"))), (state, ts)
        )


def pop_oauth_state(state: str) -> bool:
    """Single-use read: consuming the state is what makes it a CSRF defence."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(_sql("SELECT 1 FROM oauth_states WHERE state = ?"), (state,))
        if cur.fetchone() is None:
            return False
        cur.execute(_sql("DELETE FROM oauth_states WHERE state = ?"), (state,))
        return True


def is_issued(pr_key: str, user_id: str | int) -> bool:
    with _conn() as conn:
        row = _fetchone(
            conn,
            "SELECT 1 FROM issued WHERE pr_key = ? AND user_id = ?",
            (pr_key, str(user_id)),
        )
    return row is not None


def mark_issued(pr_key: str, user_id: str | int) -> None:
    with _conn() as conn:
        conn.cursor().execute(
            _sql(_insert_ignore("issued", ("pr_key", "user_id"))),
            (pr_key, str(user_id)),
        )


def put_ephemeral(key: str, data: dict, ts: float) -> None:
    with _conn() as conn:
        conn.cursor().execute(
            _sql(_upsert("ephemeral", "key", ("key", "data", "ts"))),
            (key, json.dumps(data), ts),
        )


def get_ephemeral(key: str) -> dict | None:
    with _conn() as conn:
        row = _fetchone(conn, "SELECT data FROM ephemeral WHERE key = ?", (key,))
    return json.loads(row[0]) if row else None


def pop_ephemeral(key: str) -> dict | None:
    """Single-use read. Used for the credential token so a proving session
    cannot be replayed."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(_sql("SELECT data FROM ephemeral WHERE key = ?"), (key,))
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(_sql("DELETE FROM ephemeral WHERE key = ?"), (key,))
        return json.loads(row[0])


def prune_ephemeral(older_than_ts: float) -> None:
    with _conn() as conn:
        conn.cursor().execute(
            _sql("DELETE FROM ephemeral WHERE ts < ?"), (older_than_ts,)
        )
