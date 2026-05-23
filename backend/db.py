"""SQLite persistence helpers for the anonymous review backend."""

from __future__ import annotations

import sqlite3
import os

DB_PATH = os.environ.get("DB_PATH", "backend.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = _connect()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS approvals (
                pr_key TEXT NOT NULL,
                proof_hash TEXT NOT NULL,
                PRIMARY KEY (pr_key, proof_hash)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pseudonyms (
                pr_key TEXT NOT NULL,
                pseudonym TEXT NOT NULL,
                PRIMARY KEY (pr_key, pseudonym)
            )
        """)
    conn.close()


def proof_exists(pr_key: str, proof_hash: str) -> bool:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM approvals WHERE pr_key = ? AND proof_hash = ?",
            (pr_key, proof_hash),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def pseudonym_exists(pr_key: str, pseudonym: str) -> bool:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM pseudonyms WHERE pr_key = ? AND pseudonym = ?",
            (pr_key, pseudonym),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def add_approval(pr_key: str, proof_hash: str, pseudonym: str) -> int:
    """Insert approval and pseudonym rows (INSERT OR IGNORE), return total approval count for pr_key."""
    conn = _connect()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO approvals (pr_key, proof_hash) VALUES (?, ?)",
            (pr_key, proof_hash),
        )
        conn.execute(
            "INSERT OR IGNORE INTO pseudonyms (pr_key, pseudonym) VALUES (?, ?)",
            (pr_key, pseudonym),
        )
    count = conn.execute(
        "SELECT COUNT(*) FROM approvals WHERE pr_key = ?", (pr_key,)
    ).fetchone()[0]
    conn.close()
    return count


def approval_count(pr_key: str) -> int:
    conn = _connect()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM approvals WHERE pr_key = ?", (pr_key,)
        ).fetchone()[0]
    finally:
        conn.close()
