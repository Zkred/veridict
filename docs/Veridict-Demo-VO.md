# Veridict — Demo voiceover script

**Video file:** `docs/Veridict-Demo.mp4`
**Length:** 65 s (13 frames × 5 s each)
**Aspect:** 1440 × 900, MP4 / H.264
**Recommended pacing:** ~22 words per 5-second beat (around 130 wpm — natural delivery).

---

## Frame-by-frame script

### 0:00 – 0:05 · Frame 1 · Hero
> Veridict. AI writes the code. Math approves the merge. A ZK-attested merge gate for the AI-synthesis era.

### 0:05 – 0:10 · Frame 2 · Manifesto
> Vibe-coded code shouldn't merge on vibes. It should merge on proof. That's the architectural thesis Veridict is built around.

### 0:10 – 0:15 · Frame 3 · Why we built this — four incidents
> Open source is leaking trust. Bincode died from doxxing. Xz-utils almost shipped a backdoor. Curl is drowning in AI slop. Same architectural hole every time.

### 0:15 – 0:20 · Frame 4 · The pipeline (animated)
> Three steps. One signature. Spec, synthesis, verification, credential, ZK proof, merge. Six stages in about thirty seconds end-to-end.

### 0:20 – 0:25 · Frame 5 · Verification, in the open
> If the spec doesn't hold, no proof exists. The issuer runs mypy, pytest, and Z3 against every PR before minting a credential. There is no force-approve.

### 0:25 – 0:30 · Frame 6 · ZK Proof receipt
> Reviewers prove. Identities disappear. A 360-kilobyte Longfellow proof in 10 seconds replaces the reviewer's identity with a stable, per-PR pseudonym.

### 0:30 – 0:35 · Frame 7 · Dashboard
> Sign in with GitHub. Eligibility is verified per repo, not at login — your identity stays inside the issuer. Paste a PR URL, or synthesise one fresh from a spec.

### 0:35 – 0:40 · Frame 8 · Synthesize page
> Describe what to build. Claude generates the implementation, a pytest suite, and a Z3 invariant file. A GitHub App opens the PR automatically — about ten seconds end-to-end.

### 0:40 – 0:45 · Frame 9 · Review page
> Here's a synthesised PR. Spec verification card on the right — all three formal layers green. mypy, pytest, Z3. Approval is gated on this passing.

### 0:45 – 0:50 · Frame 10 · The diff
> The reviewer reads the diff like any other PR. Standard collapsible per-file view. The bot already opened it; your only job is the qualitative judgement.

### 0:50 – 0:55 · Frame 11 · Approve anonymously
> Tick the box. Click approve anonymously. The Longfellow prover runs locally — ten seconds — and produces a ZK proof bound to this exact commit SHA.

### 0:55 – 1:00 · Frame 12 · Proving overlay
> The proof carries the issuer's signature on a one-shot MDOC credential, plus a session transcript so this approval can't be replayed on a different PR.

### 1:00 – 1:05 · Frame 13 · Receipt
> Receipt. Circuit ID, proof size, transcript hex, prover and verifier timings, pseudonym. Identity? Never disclosed. The merge gate flips green after N anonymous approvals. That's Veridict.

---

## Tips for the recording session

1. Open `docs/Veridict-Demo.mp4` in QuickTime, iMovie, or Descript.
2. Record the voiceover against this script in **one continuous take** to keep tone consistent. You can re-do individual beats and splice later.
3. Each beat is sized to 5 seconds. If you finish a line early, leave the trailing silence — it lets the visual breathe.
4. Music: optional; if used, keep it under -22 dB so the voice dominates. Suggested mood: minimal/electronic instrumental.

## Final notes

- The video has **no audio track** — bring your own voiceover.
- Total runtime is 65 seconds, right in the hackathon-recommended 60–90 s sweet spot.
- For a longer cut: hold each frame for 6–7 seconds in your editor and the script still fits.
