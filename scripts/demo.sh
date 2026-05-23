#!/usr/bin/env bash
# End-to-end demo of the anonymous review pipeline.
#
# Requires (in three other terminals):
#   A:  DEV_MODE=1 .venv/bin/python issuer/server.py
#   B:  .venv/bin/python backend/main.py
#
# Critical invariant: prover --now MUST equal verifier --now, and BOTH must
# fall inside the MDOC's validFrom..validUntil window. We freeze `now` once,
# 30 seconds in the future of mint time, and reuse it for both legs.

set -euo pipefail
cd "$(dirname "$0")/.."

ISSUER=${ISSUER:-http://localhost:8000}
BACKEND=${BACKEND:-http://localhost:8001}
PR_KEY=${PR_KEY:-myorg/myrepo/42/abc123}
PROOF_PATH=.validate/review.proof
mkdir -p .validate

step() { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }

step "[1/5] Fetching issuer public key"
PUB=$(curl -fsS "$ISSUER/issuer/pubkey")
PKX=$(printf '%s' "$PUB" | python3 -c 'import sys,json;print(json.load(sys.stdin)["pkx"])')
PKY=$(printf '%s' "$PUB" | python3 -c 'import sys,json;print(json.load(sys.stdin)["pky"])')
echo "    pkx=$PKX"

step "[2/5] Minting credential bound to $PR_KEY"
TRANSCRIPT=$(curl -fsS -D /tmp/headers \
    "$ISSUER/dev/credential?role=maintainer&pr_key=${PR_KEY}" \
    -o .validate/reviewer.mdoc \
  && grep -i '^x-transcript-hex:' /tmp/headers \
    | awk '{print $2}' | tr -d '\r\n')
echo "    mdoc: $(wc -c < .validate/reviewer.mdoc) bytes"
echo "    transcript: ${TRANSCRIPT:0:40}..."

# Freeze `now` — 30s in the future to clear validFrom comfortably.
NOW=$(python3 -c 'import datetime as d; \
print((d.datetime.now(d.timezone.utc)+d.timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ"))')
echo "    frozen now: $NOW"

step "[3/5] Generating ZK proof (~10s — circuit compile dominates)"
./prover/build/prover_cli \
  --mdoc .validate/reviewer.mdoc \
  --pkx "$PKX" --pky "$PKY" \
  --transcript "$TRANSCRIPT" \
  --claim "org.example.reviewer:role:6a6d61696e7461696e6572" \
  --now "$NOW" \
  --out "$PROOF_PATH" 2>&1 | tail -2

step "[4/5] Submitting proof to backend"
curl -fsS -X POST \
  -F "file=@${PROOF_PATH}" \
  -F "now=${NOW}" \
  "$BACKEND/pr/${PR_KEY}/proofs" | python3 -m json.tool

step "[5/5] Checking approval count"
curl -fsS "$BACKEND/pr/${PR_KEY}/approvals" | python3 -m json.tool

echo
echo "If valid_proofs == required, the GitHub Action check would pass."
echo "Re-run with PR_KEY=$PR_KEY (same) to add another approval, or with"
echo "PR_KEY=other/repo/1/sha to start a fresh PR."
