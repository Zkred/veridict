# Veridict — ZK-Attested Spec-Driven Review (Longfellow + Claude)

ZK-attested anonymous code review for AI-synthesized code. A natural-language
spec drives Claude to generate an implementation, a pytest suite, and a Z3
invariant file; the issuer signs a reviewer credential only after all three
verifications pass. Reviewers then prove they hold a qualified credential
without revealing who they are. N anonymous approvals on a specific PR commit
→ branch protection unlocks merge.

## Quickstart

```bash
# One command does everything: clone + patch + build Longfellow, build our
# prover/verifier, install Python deps, validate MDOC format.
./scripts/bootstrap.sh
```

### Configure

```bash
cp .env.example .env
$EDITOR .env   # fill in GitHub creds + org for Mode 2; leave blank for Mode 1
```

Both servers auto-load `.env` on startup.

### Mode 1 — headless smoke test (CLI only, no GitHub needed)

Set `DEV_MODE=1` in `.env`, then:

```bash
# Terminal A — issuer in dev mode
.venv/bin/python issuer/server.py

# Terminal B — backend
.venv/bin/python backend/main.py

# Terminal C — full pipeline
./scripts/demo.sh
```

A credential is minted → ZK proof generated (~10s) → submitted → backend
verifies. Run `demo.sh` twice to cross the 2-approval threshold.

### Mode 2 — real GitHub OAuth + browser UI

Fill in `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `REQUIRED_ORG` in `.env`
(see `docs/github-oauth-setup.md` for the OAuth app setup), then:

```bash
# Terminal A
.venv/bin/python issuer/server.py

# Terminal B
.venv/bin/python backend/main.py

# Browser
open http://localhost:8000
```

The UI lets a reviewer sign in, enter a PR slug, and approve anonymously.
Server resolves the HEAD SHA, mints the credential, runs the prover, and
submits to the backend — all behind a single button click.

## What you'll hit, in order

1. **MDOC namespace not registered.** Fixed by `patches/add-reviewer-namespace.patch`
   (bootstrap applies it automatically).
2. **DeviceKey label mismatch.** Longfellow uses CBOR labels `-1` for pkx and
   `-2` for pky — *not* COSE_Key's `-2`/`-3`. Fixed in `mdoc_builder.py`.
3. **DeviceSignature must be real.** The ZK circuit verifies it against the
   deviceKey from the MSO using the session transcript. `mdoc_builder.py` now
   produces a real ECDSA P-256 signature over `DeviceAuthentication`.
4. **Transcript format must match exactly.** Both issuer and backend derive
   it as `cbor2([null, null, ["AnonReviewv1", sha256(pr_key)]])`. If the two
   diverge by one byte, proofs fail.

Full parser gotchas: `docs/mdoc-format-notes.md`.

## Architecture

```
Reviewer ──► Issuer (Python, GitHub OAuth)
              │  ES256-signed MDOC, deviceSignature bound to pr_key
              ▼
            Prover (C++, Longfellow run_mdoc_prover) ──► ZK proof (~325 KB)
              │
              ▼
            Backend (Python, run_mdoc_verifier) ──► stored approval count
              ▲
              │
            GitHub Action gate
```

## Layout

- `issuer/`        — MDOC credential issuer (Python, FastAPI)
- `prover/`        — C++ CLIs wrapping Longfellow's run_mdoc_{prover,verifier}
- `backend/`       — Review backend (Python, FastAPI)
- `patches/`       — Longfellow source patches (add our namespace)
- `scripts/`       — bootstrap, demo, MDOC validation
- `docs/`          — wire format notes, design tradeoffs
- `.github/workflows/anonymous-review-check.yml` — merge gate

## Honest limitations (call these out in the demo)

1. **Issuer holds the device key.** A real deployment would have the reviewer
   generate it client-side. Easy to fix; we shipped the simpler version.
2. **Credential is bound to a specific PR.** The session transcript embeds
   the pr_key, so one credential = one PR. Need a fresh credential per PR.
3. **No nullifier.** A reviewer can request multiple credentials for the
   same PR and look like distinct reviewers. Real fix needs a nullifier
   circuit which Longfellow doesn't expose.
4. **Issuer is a trust root, not anonymous itself.** Anonymity is towards
   the verifier (CI), not the issuer.

These map to known fellowship-stage research questions and are worth flagging
honestly in the writeup.
