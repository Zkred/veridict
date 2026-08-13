# Veridict — ZK-Attested Spec-Driven Review (Longfellow + Claude)

Anonymous, cryptographically-attested code review for AI-synthesized code.

A natural-language spec drives Claude to generate an implementation, a pytest
suite, and a Z3 invariant file. The reviewed repository's own CI runs all three.
Only if they pass will the issuer mint a reviewer credential — and the reviewer
then proves they hold that credential **in their browser**, without revealing who
they are. N anonymous approvals on a specific commit flip a GitHub commit status,
and branch protection unlocks the merge.

**Live:** <https://veridict.zkred.tech>

## It works in both directions

Two pull requests on the demo repo, same gate, opposite outcomes:

| PR | Gate | Why |
|---|---|---|
| [#9](https://github.com/vayu-network/anonymous-review-demo/pull/9) | **blocks approval** | Claude's own tests were wrong: an ordering comparison against `pytest.approx`, and a test passing `rate=0` right after commenting that it is invalid |
| [#13](https://github.com/vayu-network/anonymous-review-demo/pull/13) | **permits approval** | mypy, pytest and Z3 all green in CI |

PR #9 is the point of the project: code that looks right, passes review by
eye, and fails on invariants.

## How it works

```
spec ──► Claude ──► implementation + tests + Z3 properties ──► PR (GitHub App)
                                                                │
                    reviewed repo's CI runs mypy + pytest + Z3 ─┘
                                     │ check run: veridict-spec-gate
                                     ▼
reviewer's browser                issuer  ── reads the CI verdict; refuses to
  │ generates a P-256 device key    │        issue a credential unless it passed
  │ (non-extractable, IndexedDB)    │
  │ ─── device public key ────────► │  signs an ISO 18013-5 MDOC around it
  │ ◄── credential + bytes to sign ─┘  (issuer never sees the private key)
  │
  │ signs, then proves in WebAssembly (~5 s, 360 KB proof)
  ▼
backend ──► verifies the proof in-process (wasmtime) ──► Postgres
  │
  └──► GitHub commit status `zk-review-gate`: N/M approved ──► merge unlocks
```

Three properties are worth stating precisely:

- **The issuer cannot approve on your behalf.** The device key is generated in
  the browser and never leaves it. The issuer signs a credential *around* the
  public key and hands back the exact bytes the holder must sign.
- **The formal checks never run inside the issuer.** They run in the reviewed
  repository's CI. Executing attacker-influenced PR code in the process that
  holds the signing key would be an exfiltration path.
- **Verification is server-side and needs no native binary.** The same
  WebAssembly module the browser proves with is run by the backend under
  `wasmtime`, in-process — no compiler, no subprocess, no node.

## Quickstart (local)

```bash
./scripts/bootstrap.sh      # clone + patch + build Longfellow, build the CLIs,
                            # verify the cached circuit, install Python deps
cp .env.example .env        # see docs/github-oauth-setup.md for the OAuth app
```

Run the two services:

```bash
.venv/bin/uvicorn server:app --app-dir issuer  --port 8000   # issuer + UI
.venv/bin/uvicorn main:app   --app-dir backend --port 8001   # verifier + bot
```

Then open <http://localhost:8000>, sign in, load a PR, and approve. Proving
happens in the browser; nothing is generated server-side.

To build the WebAssembly prover from source (needs `emscripten` and a zstd
checkout):

```bash
./prover/wasm/build.sh      # -> prover/wasm/dist/{veridict_prover.js,.wasm,
                            #                      veridict_standalone.wasm}
```

### Checks

```bash
./scripts/validate_v2.sh          # circuit, crypto shim, split signing, wasm
                                  # prove/verify, cross-compat, tamper rejection
./scripts/validate_db.py          # both stores, on SQLite and on Postgres
./scripts/validate_spec_gate.py   # CI gate trust logic, including spoof rejection
```

## Adopting the gate in a repository

Copy [`templates/veridict-spec-gate.yml`](templates/veridict-spec-gate.yml) to
`.github/workflows/` in the repo you want gated. The job publishes a check run
named `veridict-spec-gate`; the issuer reads its conclusion.

The issuer only trusts check runs created by GitHub Actions itself. A check run
of that name reporting success proves nothing on its own — anyone holding a
`checks:write` token could publish one — so the creating app is verified.
`SPEC_GATE_MODE` selects `ci-required` (production), `ci-preferred` (falls back
to running the checks in-process for repos without the workflow), or `local`.

## Deployment

Two Vercel projects from one repository, selected by `VERIDICT_ROLE`
(`issuer` / `backend`) via `api/index.py`, each with its own Neon Postgres
database. That separation is deliberate: one function holding both the signing
key and the GitHub App key would put reviewer identity and submitted proofs in
the same process, and a shared database would let the backend read the issuer's
pseudonym mapping.

Secrets travel as base64 environment variables (`ISSUER_KEY_B64`,
`PSEUDONYM_KEY_B64`, `GITHUB_APP_PRIVATE_KEY_B64`) because a serverless
filesystem is ephemeral and read-only. Both key loaders fail loudly rather than
generating a replacement: a rotating issuer key invalidates every credential
already issued, and a rotating pseudonym key makes one reviewer look like
several. See `.env.example`.

## Wire-format gotchas

1. **Namespaces are hardcoded.** Longfellow's parser silently ignores attributes
   in any namespace absent from `kSupportedNamespaces[]`. Registered by
   `patches/add-reviewer-namespace.patch`.
2. **DeviceKey uses standard COSE_Key.** The parser's `dev_key_pkx_` /
   `dev_key_pky_` variables are misleadingly named — they hold CBOR positions,
   not coordinates. The reference MDOC uses EC2 P-256 as spec'd: `-1: crv`,
   `-2: x`, `-3: y`.
3. **The device signature must be real.** The circuit verifies it against the
   deviceKey in the MSO using the session transcript.
4. **`now` is part of the public commitment.** Prover and verifier must be given
   byte-identical timestamps, inside the credential's validity window.
5. **The transcript must match byte-for-byte** on both sides:
   `cbor2([null, null, ["AnonReviewv1", sha256(pr_key)]])`.
6. **Circuit generation is not free** — 15 s at 1.4 GB peak RSS. It is
   deterministic per ZK spec, so the blob is committed and loaded instead,
   taking proving to ~0.5 s natively. `prover/build/circuit_tool --check`
   verifies it against `kZkSpecs`.

Full notes: [`docs/mdoc-format-notes.md`](docs/mdoc-format-notes.md).

## Layout

- `issuer/` — credential issuer, reviewer UI, CI gate reader (FastAPI)
- `issuer/static/` — browser proving: device key, worker, orchestration
- `backend/` — proof verifier + GitHub bot (FastAPI); `wasm_verifier.py` runs
  the module in-process under wasmtime
- `prover/` — C++ CLIs, `circuit_tool`, and the emscripten build
- `prover/circuits/` — the cached circuit blob, identical to Longfellow's
- `patches/` — Longfellow patches: reviewer namespace, portable crypto shim
- `templates/` — the spec-gate workflow for reviewed repositories
- `api/index.py` — Vercel entrypoint for both roles
- `docs/V2-PLAN.md` — what was built after the hackathon, and why

## Honest limitations

1. **No nullifier.** Two sessions can still produce two pseudonyms unless you
   trust the issuer, which today blocks duplicates server-side via an
   `(pr_key, user_id)` record. The cryptographic fix derives a blinded ID inside
   the circuit; that forks the circuit and diverges from upstream.
2. **Z3 proves the spec, not the implementation.** The gate establishes that the
   spec is internally consistent, the code typechecks, and the tests pass — not
   that the implementation satisfies the spec. Tests written by the same model
   that wrote the code are weak evidence, which PR #9 demonstrates.
3. **One credential per PR.** The transcript embeds the `pr_key`, so a
   force-push invalidates prior approvals — intended, but it means a fresh
   credential per commit.
4. **Admins can bypass.** Branch protection binds contributors; unless
   "Do not allow bypassing the above settings" is enabled, repo admins may merge
   without the gate.
5. **Python-only checks.** Go, Rust and C++ PRs pass through unchecked.
6. **GitHub-shaped.** The gate is a commit status and a check run. Git trailers
   would make it forge-independent.
