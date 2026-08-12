#!/usr/bin/env bash
# Validation suite for the browser-side proving stack.
#
# Covers the invariants that would silently break the trust model or the wire
# format: the cached circuit's identity, the OpenSSL replacement's byte-exactness,
# the split-signed credential (issuer signs the MSO, browser signs
# DeviceAuthentication), and prover/verifier interoperability in both directions
# between the native and WebAssembly builds.
#
#   ./scripts/validate_v2.sh
#
# Requires scripts/bootstrap.sh to have run (native CLIs, circuit blob, wasm
# module) and a .venv with the issuer's Python deps.

set -uo pipefail
cd "$(dirname "$0")/.."

CIRCUIT="prover/circuits/8d079211715200ff06c5109639245502bfe94aa869908d31176aae4016182121"
PYTHON="${PYTHON:-.venv/bin/python}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0
fail=0
check() {
  if [ "$1" -eq 0 ]; then
    printf "  \033[0;32mPASS\033[0m  %s\n" "$2"; pass=$((pass + 1))
  else
    printf "  \033[0;31mFAIL\033[0m  %s\n" "$2"; fail=$((fail + 1))
  fi
}

for required in "$CIRCUIT" prover/build/circuit_tool prover/wasm/dist/veridict_prover.js; do
  if [[ ! -e "$required" ]]; then
    echo "missing $required — run ./scripts/bootstrap.sh first" >&2
    exit 2
  fi
done

# Fixtures captured from a real issuance; see .validate/.
PKX=$(sed -n 1p .validate/ours.pubkey)
PKY=$(sed -n 2p .validate/ours.pubkey)
NOW=$(cat .validate/ours.now)
TRANSCRIPT=$(xxd -p .validate/ours.transcript | tr -d '\n')
CLAIM="org.example.reviewer:role:6a6d61696e7461696e6572"
DOCTYPE="org.example.reviewer.v1"

wasm_verify() {
  node prover/wasm/verify.cjs --proof "$1" --circuit "$CIRCUIT" \
    --pkx "$PKX" --pky "$PKY" --transcript "$TRANSCRIPT" --claim "$CLAIM" \
    --now "$NOW" --doctype "$DOCTYPE" >/dev/null 2>&1
}

echo "=== Veridict v2 validation suite ==="

./prover/build/circuit_tool --check "$CIRCUIT" --spec 0 >/dev/null 2>&1
check $? "circuit blob matches kZkSpecs[0] circuit_id"

if [[ -x prover/build/portable_crypto_difftest ]]; then
  ./prover/build/portable_crypto_difftest >/dev/null 2>&1
  check $? "portable crypto shim matches OpenSSL"
else
  echo "  SKIP  portable crypto difftest not built"
fi

"$PYTHON" scripts/validate_split_signing.py >/dev/null 2>&1
check $? "split-signed MDOC (browser device key) proves + verifies"

node prover/wasm/test/prove_node.cjs "$TMP/wasm.proof" >/dev/null 2>&1
check $? "wasm prover generates a proof"

wasm_verify "$TMP/wasm.proof"
check $? "wasm verifier accepts the wasm proof"

# Cross-compatibility in both directions is the real guarantee that the portable
# crypto shim and the native OpenSSL build agree bit for bit.
if [[ -x prover/build/verifier_cli ]]; then
  ./prover/build/verifier_cli --proof "$TMP/wasm.proof" --pkx "$PKX" --pky "$PKY" \
    --transcript "$TRANSCRIPT" --claim "$CLAIM" --now "$NOW" \
    --doctype "$DOCTYPE" --circuit "$CIRCUIT" >/dev/null 2>&1
  check $? "native verifier accepts the wasm proof (cross-compat)"
else
  echo "  SKIP  native verifier_cli not built"
fi

wasm_verify .validate/proof.bin
check $? "wasm verifier accepts a native proof (cross-compat)"

# Negative case: a verifier that accepts everything would pass every test above.
cp "$TMP/wasm.proof" "$TMP/tampered.proof"
"$PYTHON" - "$TMP/tampered.proof" <<'EOF'
import sys
p = sys.argv[1]
d = bytearray(open(p, "rb").read())
d[5000] ^= 0xFF
open(p, "wb").write(bytes(d))
EOF
if wasm_verify "$TMP/tampered.proof"; then
  check 1 "wasm verifier REJECTS a tampered proof"
else
  check 0 "wasm verifier REJECTS a tampered proof"
fi

echo
echo "  $pass passed, $fail failed"
[ "$fail" -eq 0 ]
