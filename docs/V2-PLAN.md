# Veridict v2 Plan

Target: run Veridict on Vercel's free tier, and close the three gaps Reviewer 2
raised plus the forge-coupling gap Reviewer 1 raised.

Ordering is driven by the deployment goal. Browser-side proving comes first
because it is the item that makes a free Vercel deployment possible at all, and
it happens to also be the fix for the trust-model critique.

---

## What actually blocks Vercel today

Four things, in descending order of difficulty:

| Blocker | Why it blocks | Fixed in |
|---|---|---|
| Native C++ prover invoked per approval | `prover/build/prover_cli` is a macOS binary, spawned by the issuer via subprocess | Phase 1 (moves to browser) |
| Native C++ verifier invoked per approval | Same, in the backend. Cannot move to the browser: verification must stay server-authoritative or the gate is spoofable | Phase 1 (WASM in a function) |
| `mypy` / `pytest` / Z3 on untrusted AI code | The function holding the GitHub App private key would be executing attacker-influenced Python in the same environment | Phase 2 (moves to CI) |
| SQLite with WAL on local disk | Vercel functions have no persistent writable filesystem | Phase 2 (managed store) |

Platform limits that used to be blockers and no longer are (verified against
current Vercel docs, 2026-06):

- Package size is **5 GB** on Fluid Compute, not 250 MB. A WASM module or a
  static native binary fits comfortably.
- Default function timeout is **300 s on all plans**, not 60 s. A 7 s
  verification fits with room to spare.
- Request bodies up to **100 MB**. Our proof is 360 KB (measured:
  `.validate/proof.bin` = 360,116 bytes).
- Python 3.13/3.14 is well supported, so the FastAPI apps port as-is.

Caveat to confirm before launch: Hobby-tier quotas (included compute, and the
non-commercial-use term) are separate from the platform limits above.

---

## Phase 0: Measurement spike — DONE (2026-08-12)

Every question came back favourable. Measured on this machine with the existing
Release build, via the new `prover/build/circuit_tool`.

**0.1 The reviewer-namespace patch does not affect the circuit.** Our patched
build regenerates Longfellow's shipped 1-attribute v7 circuit **byte for byte**
(both sha256 `9016d173...`, computed `circuit_id` matches the `kZkSpecs[0]` hash
`8d079211...`). Cross-checked in the other direction too: the proof committed
back in May, generated with inline circuit generation, verifies against the
cached blob. So the supported-namespace list is host-side CBOR parsing only, and
we can use Google's circuits unmodified. This is the best available outcome. It
keeps us on upstream's circuit hashes and removes the fork risk that Phase 3
Option A would otherwise inherit.

**0.2 Peak RSS is comfortably inside wasm32 limits.**

| Operation | Time | Peak RSS |
|---|---|---|
| Circuit generation (now avoided at runtime) | 15.2 s | 1.39 GB |
| Prove, cached circuit | **0.47 s** | **346 MB** |
| Verify, cached circuit | **0.83 s** | **259 MB** |

346 MB for proving is the number that matters, and it is nowhere near the ~2 GB
practical wasm32 ceiling. Browser proving is viable. Note the circuit
decompresses to 94 MB in memory (zstd 98,932,952 to 316,385 on disk), which is
included in that 346 MB.

**0.3 Verification is not remotely tight** against a 300 s function limit: 0.83 s
with the circuit cached. It was previously up to 3 x 15 s, because
`_run_verifier` retries up to three claim values and each retry regenerated the
circuit.

### Shipped as part of this spike

Circuit caching was the standalone win the plan called for, so it is wired in
rather than left as a measurement:

- `prover/src/circuit_tool.cc` with `--list`, `--generate`, `--check`.
- `--circuit <path>` on both `prover_cli` and `verifier_cli`, falling back to
  inline generation when omitted so nothing breaks.
- `prover/circuits/8d0792...` committed (316 KB), plus a `CIRCUIT_PATH` env var
  wired into both servers.
- `bootstrap.sh` step 5 re-checks the blob against `kZkSpecs[0]` rather than
  trusting it, and generates it if absent.

Net effect on the running app today, before any WASM work: **proving 10 s to
~0.5 s, verification up to 45 s to ~0.8 s.**

### Original spike definition (for reference)

Three numbers decide the shape of Phase 1. All are cheap to get with the build
that already exists at `../longfellow-zk/build/`.

**0.1 Can our patched build load Google's precompiled circuits?**

This is the highest-value question in the whole plan. `lib/circuits/mdoc/circuits/`
ships 17 precompiled circuit blobs, 210 to 340 KB each, named by circuit hash,
and the reference Go service loads them from disk with `-circuit_dir`.

Meanwhile our [prover_cli.cc:112](../prover/src/prover_cli.cc#L112) calls
`generate_circuit()` on **every single invocation**, which is where the ~8 s
goes. The code comment already says it should be cached.

The open question is whether `patches/add-reviewer-namespace.patch` invalidates
those blobs. The patch edits `kSupportedNamespaces[]` in
`mdoc_attribute_ids.h`, which is host-side CBOR parsing that builds the witness.
If the namespace list is not encoded into the circuit itself, the shipped blobs
stay valid.

- If valid: load a blob instead of generating. Proof time drops from ~10 s to
  under 1 s, verification from ~7 s to well under 1 s, and the browser
  downloads a ~250 KB asset that caches forever. This also makes Phase 3
  dramatically cheaper.
- If invalid: we generate our own circuit once, offline, commit the blob, and
  ship it as a static asset. Same runtime win, but our `circuit_hash` diverges
  from upstream and Phase 3's in-circuit option gets more expensive.

Either way, circuit caching is a standalone win that does not depend on WASM.
Do it before anything else.

**0.2 Peak resident memory of a proof run.** `/usr/bin/time -l` on the existing
prover. wasm32 caps a module at 4 GB and in practice degrades well before ~2 GB,
so if the native prover peaks above roughly 1.5 GB, browser proving needs a
rethink (or a 64-bit-memory build behind a flag).

**0.3 Verify timing with a cached circuit**, to confirm the server-side
verification budget on a 300 s function is not remotely tight.

Exit criteria: circuit strategy chosen, memory headroom known.

---

## Phase 1: Browser-side proving (the main event)

The port surface is much smaller than I expected. Two findings:

**OpenSSL is confined to 4 primitives in 2 files.** `lib/util/crypto.{h,cc}`
(147 lines total) is the entire dependency:

- `RAND_bytes` (one call site, `crypto.cc:26`)
- `SHA256_Init` / `Update` / `Final` and `SHA256_CTX`
- `EVP_aes_256_ecb` used as a PRF

There is no EC or BIGNUM use, because ECDSA verification happens *inside* the
circuit. That is the whole point of Longfellow, and it is what makes this port
tractable.

**The library core is single-threaded.** The only `pthread` reference in the
entire tree is test and benchmark linking in `lib/CMake/proofs.cmake`. This
matters more than it sounds: no pthreads means no `SharedArrayBuffer`, which
means **no COOP/COEP headers**, which means we do not break the third-party
identicon proxy (DiceBear via wsrv.nl) that the reviewer cards depend on.

### Tasks

1. ~~**`patches/portable-crypto.patch`**~~ — **DONE.** Adds
   `lib/util/portable_crypto.h`, a dependency-free SHA-256, AES-256-ECB and
   `RAND_bytes` (via `getentropy`, which emscripten routes to
   `crypto.getRandomValues`). It mirrors the OpenSSL function *names and
   signatures*, so the diff to Longfellow is 8 lines across `crypto.h` and
   `crypto.cc`: just which header gets included, behind
   `-DLONGFELLOW_PORTABLE_CRYPTO=1`. The native build is untouched and keeps
   using OpenSSL. Upstream merges stay trivial.

   Validated four ways before trusting it:
   - `prover/tests/portable_crypto_difftest.cc` (CMake target
     `portable_crypto_difftest`) diffs the shim against real OpenSSL: SHA-256
     across 20 length classes including the 55/56/57 padding edges, streamed in
     9 chunk sizes, `CopyState` snapshot semantics, 200 random AES-256-ECB
     blocks, plus FIPS-197 C.3 and the NIST `"abc"` vectors so a
     matching-but-wrong pair cannot pass silently. All pass.
   - A full Longfellow build with the shim regenerates the circuit **byte for
     byte** (sha256 `9016d173...`).
   - Shim-built prover to shim-built verifier: OK.
   - Both cross-compatibility directions between shim and OpenSSL builds: OK.
2. ~~**zstd for wasm.**~~ **DONE.** Emscripten has no zstd port, so
   `prover/wasm/build.sh` compiles it from source. Decompress side only: the
   circuit ships pre-compressed and `mdoc_generate_circuit.cc` (the sole
   compressor caller) is excluded from the wasm build. Needs
   `-DZSTD_DISABLE_ASM=1`, since the x86-64 huf_decompress assembly cannot
   target wasm.
3. ~~**`prover/wasm/` emscripten target.**~~ **DONE, and it works end to end:
   a proof generated in WebAssembly verifies against the native verifier.**

   Longfellow's own CMake turned out to be unusable for this. It does
   `find_package(GTest REQUIRED)` and `find_package(benchmark REQUIRED)` at
   configure time, and its Darwin branch injects `/opt/homebrew` include and
   link paths that would leak native libraries into a wasm build. Fortunately
   the library is header-heavy: only **12 source files** are needed, so
   `build.sh` compiles them directly rather than fighting the build system.

   | | Native | WASM (node) |
   |---|---|---|
   | Prove | 0.47 s | **5.12 s** |
   | Peak memory | 346 MB RSS | 200 MB heap |
   | Module size | - | 405 KB wasm + 15 KB JS |

   ~11x native, which is the expected range and comfortably inside what a
   spinner can cover. It is also *faster than the original hackathon flow*,
   which spent ~10 s server-side.

   Three findings worth keeping:
   - **No pthreads needed**, confirmed in practice. So no `SharedArrayBuffer`,
     so no COOP/COEP headers, so the cross-origin identicon images keep working.
   - **`-msimd128` is worth it**: 6.24 s to 5.05 s across three runs each, and it
     shrinks the module from 423955 to 405302 bytes.
   - **Do not preallocate the heap.** `INITIAL_MEMORY=448MB` measured identically
     to 64 MB, and held 470 MB where growth peaks at 200 MB.

   One design correction made along the way: validating the fetched circuit via
   `circuit_id()` cost **3.5 s**, because it decompresses and parses the whole
   circuit, duplicating what the prover does anyway. Replaced with a SHA-256 of
   the compressed blob against a digest pinned in `prover_wasm.cc`, which is 2 ms.
   `build.sh` asserts the pinned digest matches the shipped blob so the two
   cannot drift. This is a fail-fast UX guard, not a security boundary: the
   authoritative verifier is server-side, and a proof against the wrong circuit
   fails there regardless.
4. ~~**Web Worker + JS glue.**~~ **DONE.** `issuer/static/prover-worker.js` runs
   the module off the main thread and reports progress at real milestones rather
   than on a timer, so a stall is visible instead of being papered over.
   `issuer/static/approve.js` orchestrates the flow.

   One non-obvious requirement: the worker must pass `locateFile` when
   instantiating. Emscripten resolves the `.wasm` relative to the importing
   script's URL, so from `/js/prover-worker.js` it fetched
   `/js/veridict_prover.wasm` and failed instantiation on the 404 body
   (`expected magic word 00 61 73 6d, found 7b 22 64 65` — that is `{"de`).
5. **Circuit as a static asset.** Settled by Phase 0: ship
   `prover/circuits/8d0792...` (316 KB, upstream-identical) with immutable cache
   headers. The browser fetches it once and caches it forever, since the filename
   is the circuit hash.
6. ~~**Server-side verification via the same WASM module.**~~ **DONE.**
   `veridict_verify` is exported from the same module the browser proves with,
   for **+31 KB** of wasm, so one build serves both consumers.
   `prover/wasm/verify.cjs` is a drop-in replacement for `verifier_cli`: same
   flags, same exit codes (0 valid, 5 invalid), `OK` on stdout. The backend
   prefers it automatically and falls back to the native binary only if node is
   unavailable.

   Verification stays server-authoritative. The browser has the verify export
   too, but a client verifying its own proof would prove nothing; what matters is
   that the *server* no longer needs a compiled artifact.

   Verified end to end with the native verifier binary moved out of the way:
   browser prove 5.8 s, **wasm verify 3.4 s** (native was 1.8 s, so roughly 2x,
   and nowhere near the 300 s function limit).
7. ~~**Client-side device key.**~~ **DONE, cut over in one go.** No server-side
   proving path remains.

   The MDOC carries two independent signatures: `issuerAuth` over the MSO (which
   embeds the device *public* key) and `deviceSignature` over the
   SessionTranscript. Neither depends on the other, which is what makes the split
   possible:

   1. Browser generates a non-extractable P-256 key via WebCrypto, stores the
      `CryptoKey` in IndexedDB, sends only the public coordinates.
   2. `POST /approve/credential` gates on org membership and the spec check, then
      returns an MDOC with **64 zero bytes** where the device signature goes,
      plus the exact `device_tbs` bytes and the splice offset. All CBOR encoding
      stays in Python, where the seven parser invariants are already validated.
   3. Browser signs `device_tbs` (WebCrypto emits raw `r||s`, exactly what
      COSE_Sign1 wants, so no DER unwrapping), splices it in, and proves.
   4. `POST /approve/submit` forwards the proof to the backend.

   Step 4 goes **through the issuer deliberately**. The pseudonym and reputation
   chips are server-computed, so a browser posting straight to the backend could
   claim any pseudonym it liked. The issuer holds that state in a single-use
   `ephemeral` row keyed by a token. The device key still never leaves the
   browser, which is the property that matters.

   The one remaining issuer-side device key is `/dev/credential`, a DEV_MODE-only
   throwaway fixture for `scripts/demo.sh`, unreachable from the approval path.

### Acceptance criteria — all met

- A proof generated in the browser verifies against the native verifier. Driven
  end to end with Playwright against a real PR: two independent reviewers,
  distinct pseudonyms, **2 / 2, merge gate green**. Browser prove 5.8–5.9 s,
  backend verify 1.8 s.
- The device private key never appears in an issuer request.
- `docs/PROJECT.md` Honest Limitation #2 is now struck out as fixed, and the
  trust model reads "anonymity toward the verifier *and* the issuer".
- `scripts/validate_split_signing.py` covers the protocol without a browser:
  split-signed MDOC proves and verifies.

Two bugs found and fixed while verifying:

- **Pre-existing:** a revoked GitHub App credential turned an already-counted
  approval into a 500, because the commit-status push happened after
  `db.add_approval` and was allowed to raise. GitHub is now a best-effort side
  effect and `SubmitResponse.github_ok` reports the degradation.
- **Introduced by circuit caching:** the receipt's Circuit ID went blank, because
  the verifier only logged an `id:` line while *generating* a circuit and the
  backend scraped that from stderr. It now reports the known circuit hash, which
  is a better source than log scraping.

---

## Phase 1 outcome

Run `./scripts/validate_v2.sh` to check the whole stack (8 checks, all passing):
circuit identity, the OpenSSL replacement's byte-exactness, split signing, and
prover/verifier interop in both directions between native and wasm, plus a
tampered-proof rejection so a verifier that accepted everything could not pass.


**Phase 1 is complete. No native binary is required to run Veridict any more.**
Proving happens in the reviewer's browser, verification runs the same WASM module
server-side, and the C++ CLIs are now build-time tooling (`circuit_tool`) and an
optional fast path rather than a dependency.

Remaining native-only step: `circuit_tool --generate`, which produces the circuit
blob. That is a build step run once, not a request path, and its output is
committed.

Note for Phase 2: the backend currently shells out to `node verify.cjs`. A Python
function that can spawn node is not something to assume on a serverless host, so
the deployable form is either a **Node backend function** loading the module
in-process (no subprocess at all, and the cleaner end state) or `wasmtime-py`
running a standalone WASI build. Decide this while doing Phase 2 rather than
assuming the subprocess works.

## Phase 2: Vercel deployment

**Verifier shape: decided and done.** The open question was whether a Python
function could reach the verifier. Answer: it does not need to leave the process.
The module is built a second time with `-sSTANDALONE_WASM`, which targets WASI
and needs only five WASI calls plus `env.emscripten_notify_memory_growth` (a
no-op), so `wasmtime` runs it inside the backend. No node, no subprocess, no
compiled binary. `backend/wasm_verifier.py`; **2.5 s**, faster than via node
(3.4 s). Verified with both the native binary removed and `NODE_BIN` pointed at
nothing.

One trap worth recording: a standalone module built `--no-entry` is a WASI
*reactor*, so the host must call the exported `_initialize` to run C++ static
initialisers. Skipping it does not fail loudly — Longfellow's global field
objects are left zeroed and valid proofs get rejected with
`MDOC_VERIFIER_INVALID_INPUT`.

1. ~~**Two Vercel projects, not one.**~~ **DONE.** `api/index.py` serves either
   role, selected by `VERIDICT_ROLE`. Deploying twice from the same root with
   different environment variables is what keeps the boundary: the issuer project
   holds `ISSUER_KEY_B64` and `PSEUDONYM_KEY_B64` but not the GitHub App key, and
   the backend the reverse. One function holding both would put reviewer identity
   and submitted proofs in the same process.
2. ~~**State to a managed store.**~~ **DONE.** Both `db.py` modules run on
   SQLite locally and Postgres when `DATABASE_URL` is set (Neon via the
   Marketplace is the recommended provisioning path — it injects the variable).
   Queries are written once in SQLite dialect; `_sql` rewrites placeholders and
   the upsert helpers pick per-dialect syntax.

   Verified against a real Postgres in Docker, not just SQLite:
   `scripts/validate_db.py` exercises all 22 store behaviours on both, including
   that a resubmitted proof does not inflate the approval count. The full browser
   approval flow then ran end to end on Postgres with no SQLite files present.
3. ~~**Secrets to env vars.**~~ **DONE.** `ISSUER_KEY_B64`,
   `PSEUDONYM_KEY_B64`, `GITHUB_APP_PRIVATE_KEY_B64`, each taking precedence over
   its file path.

   The subtle part is failure behaviour. Both issuer keys previously
   *generated and persisted* when absent, which on a read-only serverless
   filesystem would either crash or, worse, mint a fresh key per instance: a
   rotating issuer key invalidates every credential already issued, and a
   rotating pseudonym key makes one reviewer look like several. Both now raise
   with an explanation instead.
4. ~~**Move the spec gate to GitHub Actions.**~~ **DONE** (`issuer/spec_gate.py`,
   `templates/veridict-spec-gate.yml`). A security fix rather than a porting
   convenience: `spec_checker.py` ran mypy, pytest and Z3 on PR contents inside
   the process holding the signing key, so a synthesised PR containing a
   `conftest.py` that reads the environment is an exfiltration path. On a
   serverless host that environment also carries the database URL.

   The non-obvious part is trust. A check run named `veridict-spec-gate`
   reporting success proves nothing on its own, because anyone with a
   `checks:write` token on the repo can publish one. The gate therefore only
   accepts runs whose creator is GitHub Actions (`app.slug`), which nobody else
   can register.

   Three modes via `SPEC_GATE_MODE`: `ci-required` (production), `ci-preferred`
   (default, falls back in-process so repos without the workflow still work), and
   `local`. Verified live: `ci-required` blocks the demo PR with 422 because it has
   no gate workflow, `ci-preferred` falls back and issues.

   `scripts/validate_spec_gate.py` covers 13 cases, including that a spoofed
   success is rejected, that a spoof cannot mask a genuine failure, and that a
   stale success does not outrank a newer failure after a re-run.

   This also unblocks later phases: Phase 4 can install Dafny or crosshair in CI
   without bloating a function bundle, and Phase 5 gets a forge-native home for
   the gate.
5. Point `veridict.zkred.tech` at the new deployment. It currently returns 503.

### Verified so far

The full browser approval flow runs in the exact deployment shape — `api/index.py`
entrypoint, both roles, secrets from environment variables, state in Postgres,
verification in-process via wasmtime — reaching **2 / 2, merge gate green**.
Nothing native, nothing on disk.

Note `prover/wasm/dist` is deliberately committed rather than gitignored: the
built module is needed at runtime and Vercel cannot run emscripten at build time.
`build.sh` regenerates it deterministically, and the pinned-digest check keeps it
honest.

### Still open

- **Task 4, the spec gate.** Untouched, and it is the one item that is a genuine
  security fix rather than a porting concern. Needs a workflow in each reviewed
  repository plus Checks API verification in the issuer, so it is a cross-repo
  change, not a local one.
- **Provisioning and deploying.** Creating the Neon database, the two Vercel
  projects, and pointing the domain all act on a real account, so they need an
  explicit go-ahead.

### Acceptance criteria

- Full synthesis to merge flow completes against
  `vayu-network/anonymous-review-demo` with nothing running locally.
- No secret material and no untrusted code execution in the same environment.

---

## Phase 3: Nullifier

Current state is better than `docs/PROJECT.md` claims. `issuer/db.py` has an
`issued (pr_key, user_id)` table, checked at
[server.py:470](../issuer/server.py#L470), so double-voting is already blocked
**if you trust the issuer**. What is missing is the cryptographic version that
holds when you do not.

Two options, and the honest recommendation is to do the cheap one first:

**Option A, in-circuit (the real fix).** Derive `H(reviewer_secret, pr_key)`
inside the proof and have the backend reject nullifiers it has seen. This means
new circuit gadgets, which means regenerating the circuit, which means our
`circuit_hash` permanently diverges from upstream and we inherit maintenance of
a forked circuit. Weeks, not days, and it interacts with whatever Phase 0
concluded.

**Option B, client-bound key (trust-reduced, days).** Phase 1 already puts a
non-extractable long-term key in the reviewer's browser. Have the client derive
the nullifier from it and submit it alongside a signature, with the issuer
attesting the key at credential time. This does not achieve the in-circuit
guarantee, and a colluding issuer plus client could still forge, but it removes
the issuer's unilateral ability to fabricate approvals.

Ship B, document precisely what it does and does not guarantee, and treat A as
the fellowship-scale item. Being specific about the gap is what earned credit
from Reviewer 2 last time.

---

## Phase 4: Code-to-spec verification

The substantive critique: Z3 currently validates that the *spec* is internally
consistent, not that the *implementation* satisfies it. So the strongest honest
claim the gate makes today is "typechecks, tests pass, spec is not
self-contradictory."

With the gate living in CI after Phase 2, this becomes mostly prompt and
workflow work.

1. **`crosshair` first.** Concolic execution over ordinary annotated Python.
   It finds counterexamples to `# pre:` / `# post:` contracts, installs with
   pip, and needs no second language from the synthesizer. Add it as a fourth
   check and extend the synthesis prompt to emit contracts.
2. **Dafny or Lean 4 as the stretch.** Stronger claim, much larger build: the
   synthesizer must emit an implementation plus a machine-checkable refinement
   proof, and the gate checks the proof. Worth scoping only once crosshair is
   landed and the CI harness is proven.
3. **Then, and only then, revisit spec-in-credential** (current PROJECT.md
   Future Work item 6). Embedding a spec hash as a disclosed MDOC attribute
   binds "this code satisfies spec X" to "a qualified reviewer approved it".
   Note the known blocker recorded in `docs/mdoc-format-notes.md`: only
   attributes in the hardcoded `kMdocAttributes[]` array are provable, so this
   needs a patch, and after Phase 0 we will know exactly what a circuit change
   costs.

---

## Phase 5: Git-native integration

Reviewer 1's point: the GitHub App coupling is why this only works on GitHub.

1. **Approval as a git trailer.** `Signed-off-by: zk-pseudo@reviewer-a7c2f3
   (proof:0xc0ea...)`, with the full 360 KB proof stored out of band and
   referenced by hash. Trailers are plain git, so they survive any forge.
2. **`git notes` as the proof-attachment mechanism**, pushed to a dedicated ref.
   Keeps proofs in the repo's object store without polluting commit messages.
3. **A standalone `veridict verify` CLI** that walks commits, resolves
   trailers to proofs, and reports gate status with no forge API at all. This is
   what makes the claim "works on GitLab, Gitea, or a bare remote" real rather
   than aspirational.
4. Keep the GitHub App as one adapter over this core, not as the core.

---

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| ~~Proof memory exceeds practical wasm32 limits~~ | Resolved | Measured 346 MB peak, versus a ~2 GB practical ceiling |
| ~~Namespace patch invalidates precompiled circuits~~ | Resolved | Byte-identical regeneration confirmed; we stay on upstream circuits |
| WASM proving too slow on mobile browsers | Low | Native is now 0.47 s with the circuit cached. Even a 10x WASM penalty lands under 5 s. Still measure on a real phone before claiming a number |
| 94 MB decompressed circuit strains low-end mobile | Medium | Unavoidable with this circuit. Measure on a mid-range Android before committing to mobile support |
| Hobby quotas or non-commercial term bite | Low | Confirm before pointing the domain over |
| Emscripten toolchain friction | Low | `android.sh` already solves cross-compilation for this tree; Phase 1 fallback keeps the deploy unblocked |

---

## Sequencing note

The order above optimises for a working free deployment that also fixes the
trust model. If the goal shifts to a fellowship application or another
submission, pull Phase 4 forward: code-to-spec is the critique you were actually
marked down on, and it is independent of the WASM work.
