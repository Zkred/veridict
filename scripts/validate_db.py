#!/usr/bin/env python3
"""Exercises both db layers against whichever backend DATABASE_URL selects.

The issuer and backend stores are written once in SQLite dialect and rewritten
for Postgres at runtime, so the two paths can drift silently: an upsert or
placeholder that works on SQLite may be a syntax error on Postgres, and it would
only surface in production. Run this against both.

    python3 scripts/validate_db.py                        # SQLite
    DATABASE_URL=postgresql://... python3 scripts/validate_db.py   # Postgres
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def load(name: str, path: str):
    """Loads a module by path. Both packages define `db.py`, so a plain import
    would silently pick whichever directory came first on sys.path."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


issuer_db = load("issuer_db", os.path.join(ROOT, "issuer", "db.py"))
backend_db = load("backend_db", os.path.join(ROOT, "backend", "db.py"))

failures: list[str] = []


def check(ok: bool, label: str) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        failures.append(label)


def main() -> int:
    backend = "Postgres" if issuer_db.IS_POSTGRES else "SQLite"
    print(f"=== db layer against {backend} ===")

    # Unique suffix so repeated runs against a persistent Postgres do not collide.
    tag = f"t{int(time.time() * 1000)}"

    issuer_db.init_db()
    check(True, "issuer init_db")

    sid = f"sid-{tag}"
    issuer_db.set_session(sid, {"login": "alice", "role": "admin"}, time.time())
    check(issuer_db.get_session(sid) == {"login": "alice", "role": "admin"},
          "session round trip")

    issuer_db.set_session(sid, {"login": "alice", "role": "member"}, time.time())
    got = issuer_db.get_session(sid)
    check(got is not None and got["role"] == "member", "session upsert overwrites")

    issuer_db.delete_session(sid)
    check(issuer_db.get_session(sid) is None, "session delete")

    state = f"state-{tag}"
    issuer_db.add_oauth_state(state, time.time())
    check(issuer_db.pop_oauth_state(state) is True, "oauth state pops once")
    check(issuer_db.pop_oauth_state(state) is False, "oauth state cannot be reused")

    pr_key = f"o/r/1/{tag}"
    check(issuer_db.is_issued(pr_key, "u1") is False, "is_issued false before issue")
    issuer_db.mark_issued(pr_key, "u1")
    check(issuer_db.is_issued(pr_key, "u1") is True, "mark_issued then is_issued")
    issuer_db.mark_issued(pr_key, "u1")  # must not raise on conflict
    check(True, "mark_issued is idempotent")

    key = f"pending:{tag}"
    issuer_db.put_ephemeral(key, {"pr_key": pr_key, "now": "2026-01-01T00:00:00Z"},
                            time.time())
    check(issuer_db.get_ephemeral(key) is not None, "ephemeral get (non-destructive)")
    check(issuer_db.get_ephemeral(key) is not None, "ephemeral get again")
    popped = issuer_db.pop_ephemeral(key)
    check(popped is not None and popped["pr_key"] == pr_key, "ephemeral pop returns data")
    check(issuer_db.pop_ephemeral(key) is None, "ephemeral pop is single-use")

    issuer_db.put_ephemeral(f"old:{tag}", {"x": 1}, time.time() - 10_000)
    issuer_db.prune_ephemeral(time.time() - 5_000)
    check(issuer_db.get_ephemeral(f"old:{tag}") is None, "prune_ephemeral removes stale")

    backend_db.init_db()
    check(True, "backend init_db")

    proof_hash = f"hash-{tag}"
    check(backend_db.proof_exists(pr_key, proof_hash) is False, "proof_exists false first")
    count = backend_db.add_approval(pr_key, proof_hash, f"pseudo-{tag}")
    check(count == 1, f"add_approval returns 1 (got {count})")
    check(backend_db.proof_exists(pr_key, proof_hash) is True, "proof_exists true after")
    check(backend_db.pseudonym_exists(pr_key, f"pseudo-{tag}") is True, "pseudonym_exists")

    # Resubmitting the same proof must not inflate the count.
    count = backend_db.add_approval(pr_key, proof_hash, f"pseudo-{tag}")
    check(count == 1, f"duplicate proof does not inflate count (got {count})")

    count = backend_db.add_approval(pr_key, f"hash2-{tag}", f"pseudo2-{tag}")
    check(count == 2, f"second distinct proof counts (got {count})")
    check(backend_db.approval_count(pr_key) == 2, "approval_count matches")

    print()
    if failures:
        print(f"  {len(failures)} FAILURES: {failures}")
        return 1
    print("  all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
