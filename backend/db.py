"""Persistence for the anonymous review backend.

Runs on SQLite locally and Postgres when DATABASE_URL is set. Serverless hosts
have no durable filesystem, so SQLite there would silently lose every approval on
the next cold start; the recommended provisioning path is Neon Postgres through
the Vercel Marketplace, which injects DATABASE_URL automatically.

The two dialects differ in three ways that matter here: parameter placeholders
(`?` vs `%s`), upsert syntax, and the absence of PRAGMA on Postgres. `_sql`
rewrites placeholders so every query below can be written once, in SQLite form.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator, Sequence

DB_PATH = os.environ.get("DB_PATH", "backend.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
IS_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))

if IS_POSTGRES:  # pragma: no cover - exercised via DATABASE_URL
    import psycopg


def _sql(query: str) -> str:
    """SQLite's `?` placeholders to Postgres's `%s`."""
    return query.replace("?", "%s") if IS_POSTGRES else query


# Upsert-ignore differs between the dialects; the conflict target is implicit on
# SQLite and must be named on Postgres for a multi-column primary key.
def _insert_ignore(table: str, columns: tuple[str, ...]) -> str:
    cols = ", ".join(columns)
    marks = ", ".join("?" for _ in columns)
    if IS_POSTGRES:
        return f"INSERT INTO {table} ({cols}) VALUES ({marks}) ON CONFLICT DO NOTHING"
    return f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({marks})"


@contextmanager
def _conn() -> Iterator[Any]:
    """Yields a connection, committing on success and closing either way."""
    if IS_POSTGRES:
        conn = psycopg.connect(DATABASE_URL)
    else:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        # WAL keeps concurrent readers from blocking on the writer. Postgres
        # needs no equivalent.
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS approvals (
                pr_key TEXT NOT NULL,
                proof_hash TEXT NOT NULL,
                PRIMARY KEY (pr_key, proof_hash)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pseudonyms (
                pr_key TEXT NOT NULL,
                pseudonym TEXT NOT NULL,
                PRIMARY KEY (pr_key, pseudonym)
            )
        """)


def proof_exists(pr_key: str, proof_hash: str) -> bool:
    with _conn() as conn:
        row = _fetchone(
            conn,
            "SELECT 1 FROM approvals WHERE pr_key = ? AND proof_hash = ?",
            (pr_key, proof_hash),
        )
    return row is not None


def pseudonym_exists(pr_key: str, pseudonym: str) -> bool:
    with _conn() as conn:
        row = _fetchone(
            conn,
            "SELECT 1 FROM pseudonyms WHERE pr_key = ? AND pseudonym = ?",
            (pr_key, pseudonym),
        )
    return row is not None


def add_approval(pr_key: str, proof_hash: str, pseudonym: str) -> int:
    """Records the approval and its pseudonym, returning the count for pr_key.

    Both inserts ignore conflicts: a resubmitted proof must not inflate the
    count, and the same reviewer's pseudonym recurs on re-approval.
    """
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            _sql(_insert_ignore("approvals", ("pr_key", "proof_hash"))),
            (pr_key, proof_hash),
        )
        cur.execute(
            _sql(_insert_ignore("pseudonyms", ("pr_key", "pseudonym"))),
            (pr_key, pseudonym),
        )
        cur.execute(
            _sql("SELECT COUNT(*) FROM approvals WHERE pr_key = ?"), (pr_key,)
        )
        return cur.fetchone()[0]


def approval_count(pr_key: str) -> int:
    with _conn() as conn:
        row = _fetchone(
            conn, "SELECT COUNT(*) FROM approvals WHERE pr_key = ?", (pr_key,)
        )
    return row[0] if row else 0
