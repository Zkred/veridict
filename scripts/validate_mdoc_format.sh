#!/usr/bin/env bash
# Run the full MDOC format compatibility validation.
#
# Steps:
#  1. Extract the known-good test MDOC from Longfellow's mdoc_examples.h
#  2. Inspect it (this is the ground truth)
#  3. Generate one with our mdoc_builder
#  4. Inspect ours
#  5. Diff the two structurally
#
# Optional: if Longfellow is built, exercise run_mdoc_prover against both.

set -euo pipefail
cd "$(dirname "$0")/.."

LF_ROOT="${LF_ROOT:-../longfellow-zk}"
HEADER="$LF_ROOT/lib/circuits/mdoc/mdoc_examples.h"

if [[ ! -f "$HEADER" ]]; then
  echo "ERROR: cannot find $HEADER"
  echo "Set LF_ROOT=/path/to/longfellow-zk or clone:"
  echo "  git clone https://github.com/google/longfellow-zk $LF_ROOT"
  exit 1
fi

mkdir -p .validate
echo "==> [1/4] Extracting reference MDOC from Longfellow test data"
python scripts/extract_reference_mdoc.py \
    --header "$HEADER" --index 0 --out .validate/reference.mdoc

echo
echo "==> [2/4] Inspecting reference MDOC (this is what Longfellow accepts)"
python scripts/inspect_mdoc.py .validate/reference.mdoc | tee .validate/reference.inspect

echo
echo "==> [3/4] Generating our MDOC with mdoc_builder.py"
PYTHONPATH=issuer python - <<'PY'
from mdoc_builder import Attribute, build_mdoc, load_or_create_issuer_key
from cryptography.hazmat.primitives.asymmetric import ec
issuer_key = load_or_create_issuer_key(".validate/issuer.pem")
device = ec.generate_private_key(ec.SECP256R1())
mdoc_bytes, transcript = build_mdoc(
    [Attribute("role", "maintainer"), Attribute("org", "myorg")],
    issuer_key, device, pr_key="myorg/myrepo/42/abc123",
)
open(".validate/ours.mdoc", "wb").write(mdoc_bytes)
open(".validate/ours.transcript", "wb").write(transcript)
print(f"wrote {len(mdoc_bytes)} bytes to .validate/ours.mdoc")
print(f"transcript: {transcript.hex()}")
PY

echo
echo "==> [4/4] Inspecting our MDOC"
python scripts/inspect_mdoc.py .validate/ours.mdoc | tee .validate/ours.inspect

echo
echo "==> Structural diff (everything below this line should be empty for full compatibility):"
echo "--- reference"
echo "+++ ours"
diff -u .validate/reference.inspect .validate/ours.inspect || true

echo
echo "Reminder: even if structure matches, you still need:"
echo "  1. patches/add-reviewer-namespace.patch applied to Longfellow"
echo "  2. A real device signature for full end-to-end verification"
echo "     (the parser accepts a stub, the ZK circuit does not)"
