# Veridict — ZK-Attested Spec-Driven Review

> *verified + verdict.* A merge gate for AI-synthesized code.
>
> Reviewers prove they are qualified — without revealing who they are.
> The merge button flips green only when N independent anonymous reviewers approve.
> The issuer only signs credentials after formal spec verification passes
> (mypy + pytest + Z3).

Built for the **Secure Program Synthesis Hackathon (May 22–24, 2026)**.

---

## TL;DR

We built a full **secure program synthesis pipeline** on top of Google Longfellow ZK:

1. A maintainer writes a **natural-language specification**.
2. **Claude API synthesizes** a Python implementation + test suite from the spec and opens a GitHub PR automatically.
3. During review, the issuer fetches the PR files and runs **mypy + pytest** — formal spec conformance checks. If either fails, no ZK credential is issued.
4. A qualified reviewer reads the diff in our UI; a **green spec check banner** confirms the code is formally verified before they approve.
5. The issuer mints a one-shot **MDOC credential** bound to that exact commit, runs Longfellow's prover (~10 s, 360 KB proof), and submits the proof to the backend.
6. The backend verifies the proof and, as a **GitHub App bot**, posts an anonymous comment and pushes a commit status driving branch protection.
7. After N approvals, the **merge button enables** on GitHub. CI, PR author, and the bot never learn who any reviewer is.

The demo runs against a real public repo
([vayu-network/anonymous-review-demo](https://github.com/vayu-network/anonymous-review-demo))
with real branch protection.

---

## The Problem

> "We have no way of knowing if what we're vibecoding does what we think it does."
> — hackathon brief

AI-generated code still needs **expert human review**. But review today
has problems that scale badly when most code is machine-written:

- **No formal gate.** AI synthesis produces code that typechecks superficially but violates spec invariants. Without automated verification before review, humans are the only line of defence.
- **Reviewer bias.** Junior engineers defer to seniors; people approve
  code that *looks* authoritative because of who wrote/reviewed it.
- **Identity-coupling makes review costly.** Senior engineers can't
  comfortably critique a peer's AI-generated code on a public PR without
  social cost.
- **Expert pools shrink to people with write access.** External security
  auditors or domain experts can't vote on a PR's merge unless the repo
  admin invites them as collaborators, which defeats the point of having
  outside review.

We want: **proof a reviewer is qualified**, **unlinkability of identity**,
**automated formal verification before any human approval is accepted**,
**no requirement of repo write access for the reviewer**.

---

## Our Solution

> Each anonymous approval = a ZK proof that the reviewer holds an MDOC
> credential signed by a trusted issuer, attesting that the holder is a
> member of the project's org with the right role — **and that the code
> passed mypy + pytest before the credential was issued**.

```
Spec (natural language)
  │
  ├─[0]──► Claude API  (synthesis)
  │        Generates implementation + pytest test suite.
  │        GitHub App opens a PR automatically.
  │
  └──── Reviewer opens the PR in our UI
          │
          ├─[1]──► Issuer  (GitHub OAuth gated)
          │        Verifies you're in REQUIRED_ORG.
          │        Fetches PR files, runs mypy + pytest.
          │        Gate: if either fails → no credential, no proof.
          │        Mints an ES256-signed MDOC credential bound to
          │        the PR's HEAD commit SHA.
          │
          ├─[2]──► Prover  (Longfellow C++)
          │        run_mdoc_prover → 360 KB ZK proof. Public inputs:
          │        issuer pubkey, session transcript (= sha256 of the
          │        PR key), claim (role = "maintainer"), current time.
          │
          └─[3]──► Backend  (Python FastAPI)
                   run_mdoc_verifier checks the proof. If valid:
                     - increments approval count
                     - pushes zk-review-gate commit status (pending/success)
                     - posts anonymous PR comment with pseudonym + chips
                          ▲
                          │
                   Branch protection requires zk-review-gate ✓ → merge unlocks.
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Synthesis                                               │
│  Spec text ──► Claude API ──► code + tests ──► GitHub PR│
└──────────────────────────────────────────────────────────┘
                                         │
                                         ▼ reviewer opens PR
┌──────────────┐   OAuth + spec check   ┌──────────────────┐
│  Reviewer    │ ──────────────────────► │     Issuer       │
│  (browser)   │                         │  mypy + pytest   │
│              │ ◄── MDOC + transcript ──│  gate: pass only │
└──────┬───────┘                         └──────────────────┘
       │ ZK proof submission
       ▼
┌──────────────┐   run_mdoc_verifier    ┌──────────────────┐
│   Backend    │ ──────────────────────►│   Longfellow     │
│   (Python)   │                        │   verifier       │
└──────┬───────┘                        └──────────────────┘
       │ as GitHub App bot
       ▼
┌──────────────┐
│   GitHub     │ ← commit status, PR comment, branch protection
└──────────────┘
```

Two distinct GitHub trust roots:

| | Used by | Auth | Scope |
|---|---|---|---|
| **OAuth App** "Anonymous Review" | reviewers signing in | client id + secret | `read:org` |
| **GitHub App** "anonymous-review-bot" | synthesis + status push + comments | App ID + private key → installation token | `contents:write`, `pull_requests:write`, `commit_statuses:write`, `issues:write` |

Reviewers prove qualification; the bot is the only thing with repo write
permission.

---

## Features Built

### AI Code Synthesis

- **`/synthesize` page**: reviewer writes a natural-language spec and
  picks a target repo. Claude API generates a Python implementation +
  pytest test suite using structured file output (`--- filename: ... ---`
  blocks). The GitHub App creates a branch, commits the files, and opens
  a PR automatically. The UI redirects straight to the review flow.
- **Stepped loading overlay** during synthesis showing the Claude call,
  code generation, and PR creation phases.
- **Repo input accepts URLs**: `https://github.com/owner/repo`,
  `github.com/owner/repo`, `owner/repo`, or `.git` suffix — all parsed
  by the same regex.

### Formal Spec Verification Gate

- **`spec_checker.py`**: fetches full Python file content for every file
  in the PR from `raw.githubusercontent.com` at the PR head SHA.
  Writes files to a temp directory, runs:
  - `mypy --ignore-missing-imports` — type safety
  - `pytest --tb=short -q` — test correctness (if test files present)
- **Hard gate**: the issuer **refuses to issue an MDOC credential** if
  either check fails. No credential → no proof → no approval possible.
  Spec check is re-run server-side at approve time (cannot be spoofed
  by a tampered client).
- **Review page banner**: green `✓ Spec check passed · mypy ✓ · pytest ✓`
  or red `✗ Spec check failed — approval blocked` with collapsible
  mypy/pytest output. Approve button is disabled until spec check passes.
- **Reputation chip**: `mypy+pytest ✓` appears in the anonymous PR
  comment alongside the reviewer's role and account age.

### Identity Layer

- **GitHub OAuth sign-in** with org-membership check (`read:org` scope).
- **Dev-mode bypass** (`/dev/login`) for UI demos without OAuth.
- **Session top bar** showing `@username` and a working **Sign out** that
  revokes the OAuth grant (so re-login forces the GitHub consent screen).

### Credential Issuance

- **Longfellow-compatible MDOC builder** (`issuer/mdoc_builder.py`):
  ISO 18013-5-format CBOR document, ES256 issuer signature, real
  ECDSA device signature, validity window, value digests of all
  attributes.
- **Custom namespace** `org.example.reviewer` registered in Longfellow
  via `patches/add-reviewer-namespace.patch` (Longfellow's parser only
  scans a hardcoded `kSupportedNamespaces[]` list).
- **Session transcript binding**: each credential is bound to a specific
  `pr_key = owner/repo/N/sha`. A force-push changes the SHA → all prior
  approvals invalidated.

### Prover / Verifier

- **C++ CLIs** wrapping Longfellow's `run_mdoc_prover` and
  `run_mdoc_verifier`. Linked against the single bundled
  `libmdoc_static.a` archive.
- With the circuit cached (`prover/circuits/`, loaded via `--circuit`),
  proving takes ~0.5 s and verifying ~0.8 s. Generating the circuit
  inline instead costs ~15 s at 1.4 GB peak RSS, which is what the
  original hackathon build did on every approval.
- **CMake auto-detects** Longfellow build artifacts and brew prefixes
  (`google-benchmark`, `zstd`, `openssl@3`).
- **Validation tooling**: `scripts/extract_reference_mdoc.py` pulls a
  known-good MDOC from Longfellow's test data;
  `scripts/inspect_mdoc.py` runs all seven parser invariants as OK/FAIL
  checks; `scripts/validate_mdoc_format.sh` round-trips both.

### Reviewer UI

- **PR URL parsing** (regex): accepts `https://github.com/...pull/42`,
  `owner/repo/42`, `owner/repo/42/sha`, with or without trailing path
  fragments (`/files`, `/commits`).
- **Diff viewer**: fetches PR + files from the GitHub API,
  renders each file as a collapsible per-file diff with green/red
  unified-diff colouring.
- **Spec check banner** prominently placed before the diff — green pass
  or red block with expandable error output.
- **"I've reviewed these changes" gate** — approve button disabled
  until checked. Also hard-disabled if spec check failed.
- **Stepped loading overlay** during proof generation, showing the
  six circuit/proof phases.
- **Polished dashboard** with role badge, signed-in chip, dark-mode
  support, and "Synthesize with AI →" entry point.

### Anonymous Identity at Presentation Time

- **Per-PR pseudonym** = HMAC-SHA256(server secret, `user_id:pr_key`)
  truncated to 6 hex chars. Same reviewer + same PR → same tag;
  different PR → unlinkable tag. The secret lives at
  `.secrets/pseudonym-key.bin` (0600).
- **Deterministic identicon** per pseudonym (DiceBear → wsrv.nl
  proxy applies a circle mask with theme-matching background via
  `<picture>` element).
- **Reputation chips** in every comment: bucketed signals from the
  reviewer's OAuth profile — role (maintainer/reviewer), `Xy+ on
  GitHub`, `100+ public repos`, `mypy+pytest ✓`. Coarse on purpose so
  they reveal trust without enabling triangulation.

### Bot Identity (the Architectural Fix)

- **GitHub App "anonymous-review-bot"** with custom logo
  (`assets/bot-avatar.svg|png`). Installation-token-based auth: JWT
  signed with App private key → POST `/app/installations/.../access_tokens`
  → use the installation token for subsequent calls (cached with 5-min
  expiry buffer).
- Posts comments as **`@anonymous-review-bot[bot]`** — the GitHub UI
  shows a **Bot** badge.
- Creates synthesis branches and PRs (`contents:write` + `pull_requests:write`).
- Pushes the commit status that drives branch protection.

### Comments

- Anonymous reviewers can attach an optional **freeform comment** to
  their approval; same ZK proof gates both. Comment body is rendered
  with floated avatar, pseudonym + reputation header, divider, body
  block underneath.
- All comments authored by the bot (truthful); pseudonym + identicon
  inside the body distinguish reviewers within a PR.

### Merge Gate

- **Backend pushes `zk-review-gate` commit status** to GitHub on every
  accepted proof: `pending` while count < N, `success` once count ≥ N,
  with a human-readable description (`2 / 2 anonymous reviewers
  approved — merge gate green`).
- **Branch protection** on `main` configured to require the
  `zk-review-gate` context (source: Any) — GitHub's native enforcement,
  no custom bot impersonation.

### Configuration & Path Handling

- **`.env`** with `python-dotenv` auto-loading at startup of both
  servers. All toggles in one file (OAuth secrets, App ID, key path,
  Anthropic key, required approvals).
- **`_resolve()` helper** in both issuer and backend: all paths from
  `.env` (prover binary, private key, pseudonym key) are resolved
  relative to the project root so servers can run from their
  subdirectories without breaking.
- **`.gitignore`** keeps `.env`, `*.pem`, `.venv/`, build dirs out of
  source control.

### Bootstrap & Demo

- **`scripts/bootstrap.sh`**: one command does the whole environment —
  installs brew deps (`googletest google-benchmark zstd openssl@3`),
  clones Longfellow, applies our patch, builds Longfellow Release,
  builds our prover/verifier CLIs, installs Python deps in a venv, runs
  MDOC format validation.
- **`scripts/expose.sh`**: ngrok/cloudflared tunnel for the backend so
  GitHub Actions (or the GitHub App webhook in a fuller deployment) can
  reach it.

---

## Wire-format Gotchas We Burnt Time On

Documented in `docs/mdoc-format-notes.md`. Highlights:

1. **Hardcoded supported namespaces.** Longfellow's parser silently
   ignores attributes in any namespace not listed in
   `lib/circuits/mdoc/mdoc_attribute_ids.h`. Required a patch.
2. **DeviceKey labels.** The parser variables `dev_key_pkx_` /
   `dev_key_pky_` look up CBOR keys `-1` and `-2`, which led us astray —
   in reality the reference MDOC uses **standard COSE_Key for EC2 P-256**
   (`-1: crv, -2: x, -3: y`).
3. **`now` is part of the public commitment.** Prover and verifier must
   be invoked with byte-identical timestamp strings, and the timestamp
   must fall inside the MDOC's validity window. Backend bounds skew to
   ±1 h.
4. **GitHub strips inline CSS.** The reviewer-card layout uses the
   `align="left"` float trick + `<br clear="left"/>`, since
   `style="vertical-align: middle"` doesn't survive sanitization.
5. **`spec_check` not in `kMdocAttributes[]`.** Embedding spec check
   result as an MDOC attribute causes the prover to fail — only
   attributes registered in the hardcoded C++ array are parseable.
   The attestation is implicit instead: the issuer simply does not sign
   credentials when spec check fails.
6. **Relative paths break when running from subdirectories.** `.env`
   paths like `./prover/build/prover_cli` resolve to
   `issuer/prover/build/prover_cli` when the server runs from `issuer/`.
   Fixed with a `_resolve()` helper in both servers.

---

## Trust Model

| Actor | Sees | Can do | Cannot do |
|---|---|---|---|
| Reviewer | own credential, own proof, spec check result | approve PR, post comment | learn other reviewers' identities |
| Issuer | reviewer's OAuth identity, pseudonym mapping, spec check result | mint credentials (only after spec check passes) | merge code, see how reviewer voted on what |
| Backend | proofs, pseudonyms, approval counts | verify, post bot comments, push status | learn reviewer identities |
| PR author / GitHub UI | bot comments tagged with pseudonyms + reputation chips, commit status | nothing extra | learn reviewer identities |

Anonymity is **toward the verifier** (CI / PR author / external audit
trail) — not toward the issuer. A fellowship-stage hardening would push
proving client-side (browser WASM) so the issuer never sees the device
key. Captured honestly in the README and the demo writeup.

---

## Honest Limitations

1. **No nullifier.** A reviewer can sign in twice (two sessions) and
   submit two approvals on the same PR — they look like two different
   pseudonyms. Longfellow doesn't easily expose a nullifier construct.
   Production fix: derive a deterministic blinded ID from
   `(reviewer_secret, pr_key)` inside the circuit so duplicates collide.
2. **Issuer-held device key.** For demo speed the issuer mints a fresh
   device key each session. A proper deployment would have the reviewer
   generate this client-side and send only the device pubkey.
3. **Pseudonym key compromise.** If the HMAC secret leaks, pseudonyms
   become enumerable against the org membership list. Store this as
   carefully as any other production secret.
4. **Comment author is one bot.** Multiple anonymous reviewers all
   appear under `@anonymous-review-bot[bot]`. Distinct identity per
   reviewer would require a pool of bot accounts (collapses anonymity
   if pool is small) — we chose pseudonym + identicon inside the comment
   body instead.
5. **Spec check is Python-only.** mypy + pytest only runs on `.py`
   files. PRs with Go, Rust, or C++ code are given a pass-through
   (skipped, not blocked). Production would add per-language checks.
6. **In-memory approval store.** Approvals are lost on backend restart.
   Production would persist to a database keyed by `pr_key`.

---

## Demo Run

A live demo is set up in
[`vayu-network/anonymous-review-demo`](https://github.com/vayu-network/anonymous-review-demo).
Real branch protection requires the `zk-review-gate` context (source: Any)
to be `success` before `main` accepts a merge.

```bash
# One-shot setup (clone Longfellow, patch, build, install Python deps).
./scripts/bootstrap.sh

# Add to .env:
#   ANTHROPIC_API_KEY=sk-ant-...
#   GITHUB_APP_ID / PRIVATE_KEY_PATH / INSTALLATION_ID

# Terminal A — issuer (OAuth + UI on :8000)
cd issuer && ../.venv/bin/uvicorn server:app --port 8000

# Terminal B — backend (verifier + bot on :8001)
cd backend && ../.venv/bin/uvicorn main:app --port 8001
```

### Full synthesis → review → merge flow

1. Open <http://localhost:8000>, **Sign in with GitHub**.
2. Click **Synthesize with AI →**, write a spec, enter the repo URL.
3. Claude generates code + tests, the bot creates the PR (~10 s).
   You're redirected to the review page.
4. Green spec check banner confirms **mypy + pytest passed**.
5. Read the diff, write a comment, tick the box, **Approve anonymously**.
6. ~10 s later: result page shows your pseudonym; PR on GitHub shows a
   new bot comment with reputation chips; commit status flips to
   `pending: 1 / 2`.
7. Open an incognito window, repeat as a second reviewer (different pseudonym).
8. Commit status flips to `success: 2 / 2 — merge gate green`.
   The **Merge** button on the PR enables.

### Review-only flow (existing PR)

1. Paste a PR URL on the dashboard and **Load PR & review**.
2. Spec check runs automatically on the PR's Python files.
3. If check passes: approve normally. If it fails: the approve button
   is blocked — the code must be fixed first.

---

## What We Learned About Longfellow

- The MDOC parser is **strict** but well-documented in the source.
  Reading `mdoc_witness.h` and `mdoc_constants.h` was the unblocker.
- The library's main C API (`run_mdoc_prover` / `run_mdoc_verifier`) is
  clean to wrap. The ECDSA / SHA circuits are too low-level for the
  3-day hackathon scope.
- Circuit compilation is the slow part and it is worth caching: ~15 s and
  1.4 GB peak RSS to generate, versus ~0.5 s to prove and ~0.8 s to verify
  once the blob is loaded from disk. The blob is 316 KB compressed and
  decompresses to 94 MB. Longfellow ships pre-generated circuits in
  `lib/circuits/mdoc/circuits/`, named by circuit hash, and our
  reviewer-namespace patch does not change them: our build regenerates one
  byte-for-byte. `circuit_tool --check` asserts that.
- ~360 KB per proof. Storeable in a database; too big for HTTP headers
  or PR comments.
- Only attributes registered in `kMdocAttributes[]` can be proved.
  Embedding new attributes requires a source patch and rebuild.

---

## File Map

```
secure-program-synthesis-hackathon/
├── README.md                  - quickstart, mode 1/2 explanation
├── docs/
│   ├── PROJECT.md             - this document
│   ├── mdoc-format-notes.md   - the seven parser invariants
│   ├── github-oauth-setup.md  - OAuth + .env walkthrough
│   └── real-repo-setup.md     - branch protection + ngrok flow
├── issuer/
│   ├── mdoc_builder.py        - MDOC issuance (CBOR + COSE_Sign1)
│   ├── server.py              - FastAPI: OAuth, UI, pseudonym, prover invocation
│   ├── synthesizer.py         - Claude API synthesis + GitHub PR creation
│   ├── spec_checker.py        - mypy + pytest formal verification gate
│   └── templates.py           - inline HTML templates with theme support
├── backend/
│   ├── main.py                - FastAPI: verifier, bot push, comment posting
│   └── gh_app.py              - GitHub App JWT → installation token helper
├── prover/
│   ├── src/{prover_cli,verifier_cli}.cc - Longfellow CLI wrappers
│   ├── src/circuit_tool.cc    - generate / inspect / validate circuit blobs
│   ├── circuits/<hash>        - cached circuit, loaded via --circuit
│   └── CMakeLists.txt         - links libmdoc_static.a + OpenSSL + zstd
├── patches/
│   └── add-reviewer-namespace.patch - registers org.example.reviewer in Longfellow
├── scripts/
│   ├── bootstrap.sh           - one-shot env setup
│   ├── expose.sh              - ngrok tunnel for the backend
│   ├── demo.sh                - end-to-end smoke test
│   └── validate_mdoc_format.sh - parser invariant checker
├── assets/
│   └── bot-avatar.{svg,png}   - GitHub App logo
├── .secrets/
│   ├── app-private-key.pem    - GitHub App private key (gitignored)
│   └── pseudonym-key.bin      - HMAC key for per-PR pseudonyms
└── .env                       - all configuration (gitignored)
```

---

## Future Work

If invited to the fellowship, the natural extensions:

1. **Nullifier circuit.** Derive a deterministic blinded ID inside the
   ZK circuit so a reviewer can't double-vote even across sessions.
   Bounds anonymity correctly.
2. **Browser-side proving.** Compile Longfellow to WASM so the issuer
   never sees the device key. The issuer becomes a pure attestation
   service.
3. **Inline review comments**, not just top-level. The bot already has
   `pull_requests:write`; the API supports `POST /pulls/{N}/reviews`
   with file/line locations.
4. **ZK reputation aggregation.** Today the reputation chips are
   coarse facts ("5y+ on GitHub"). With a richer credential schema we
   could prove things like "approved ≥ 10 prior PRs in this org" or
   "domain badge: cryptography" without revealing the underlying audit
   log.
5. **Multi-issuer.** Today one issuer per deployment. A federated
   model lets reviewers from different orgs cross-review with verifier
   knowing only "credential from one of these trusted issuers".
6. **Spec-in-credential.** Today the spec check is a hard gate at
   issuance time. The next step: embed the spec hash in the MDOC as a
   disclosed attribute so the ZK proof cryptographically binds
   "this code satisfies spec X" to "a qualified reviewer approved it".
7. **Multi-language spec checking.** Extend the formal gate beyond
   Python — add Dafny for correctness proofs, `cargo test` for Rust,
   or property-based testing with Hypothesis.

---

## Acknowledgements

- **Google Longfellow ZK** — the protocol primitives + clean C API made
  this hackathon-feasible.
- **Anthropic Claude API** — code synthesis from natural-language specs.
- **DiceBear identicons** + **wsrv.nl** image proxy — per-reviewer
  visual identity.
- **GitHub Apps & Branch Protection API** — the integration points that
  let a local prototype gate a real PR end-to-end.
