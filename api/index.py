"""Vercel Function entrypoint for both Veridict services.

One file, two roles, selected by the VERIDICT_ROLE environment variable:

    VERIDICT_ROLE=issuer    the reviewer UI, OAuth, and credential issuance
    VERIDICT_ROLE=backend   proof verification and the GitHub bot

Deploy this repository as **two Vercel projects** with the same root directory
and different environment variables. That is what keeps the trust boundary
intact: the issuer project holds ISSUER_KEY_B64 and PSEUDONYM_KEY_B64 but not
the GitHub App key, and the backend project holds the App key but neither issuer
secret. Collapsing them into one function would put reviewer identity and
submitted proofs in the same process, which is exactly the correlation the whole
design exists to prevent.

Both services expect to import their own modules unqualified (`import db`), so
the relevant directory goes on sys.path rather than restructuring them into
packages.
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROLE = os.environ.get("VERIDICT_ROLE", "issuer").strip().lower()

if ROLE == "backend":
    sys.path.insert(0, os.path.join(_ROOT, "backend"))
    from main import app  # noqa: F401  (Vercel discovers `app`)
elif ROLE == "issuer":
    sys.path.insert(0, os.path.join(_ROOT, "issuer"))
    from server import app  # noqa: F401
else:
    raise RuntimeError(
        f"VERIDICT_ROLE must be 'issuer' or 'backend', got {ROLE!r}"
    )
