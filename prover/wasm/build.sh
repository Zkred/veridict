#!/usr/bin/env bash
# Build the browser-side prover: Longfellow + zstd -> WebAssembly.
#
# Longfellow's own CMake is not usable here. It does find_package(GTest REQUIRED)
# and find_package(benchmark REQUIRED) at configure time, and its Darwin branch
# injects /opt/homebrew include and link paths that would leak native libraries
# into a wasm build. The library is header-heavy enough that compiling the twelve
# sources we need directly is simpler and less fragile than patching their build.
#
# Requires: emscripten (brew install emscripten), a patched Longfellow checkout
# (scripts/bootstrap.sh), and a zstd source tree.
#
#   ./prover/wasm/build.sh
#
# Outputs prover/wasm/dist/veridict_prover.{js,wasm}

set -euo pipefail
cd "$(dirname "$0")/../.."

LF_ROOT="${LF_ROOT:-../longfellow-zk}"
ZSTD_ROOT="${ZSTD_ROOT:-../zstd}"
OUT_DIR="prover/wasm/dist"
OBJ_DIR="prover/wasm/obj"

if ! command -v emcc >/dev/null; then
  # Homebrew installs the real toolchain under libexec.
  if [[ -d /opt/homebrew/opt/emscripten/libexec ]]; then
    export PATH="/opt/homebrew/opt/emscripten/libexec:$PATH"
  else
    echo "emcc not found. brew install emscripten" >&2
    exit 1
  fi
fi

if [[ ! -f "$LF_ROOT/lib/util/portable_crypto.h" ]]; then
  echo "Longfellow checkout is missing the portable-crypto patch." >&2
  echo "Run scripts/bootstrap.sh first." >&2
  exit 1
fi

if [[ ! -d "$ZSTD_ROOT/lib/decompress" ]]; then
  echo "zstd sources not found at $ZSTD_ROOT" >&2
  echo "  git clone --depth 1 --branch v1.5.6 https://github.com/facebook/zstd.git $ZSTD_ROOT" >&2
  exit 1
fi

step() { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }

step "Checking the pinned circuit digest matches the shipped blob"
# prover_wasm.cc hard-codes the SHA-256 of the circuit it expects, so the browser
# can reject a wrong asset in milliseconds. If someone regenerates or bumps the
# circuit without updating that constant, every proof attempt would fail at
# runtime with a confusing error. Catch it here instead.
CIRCUIT_BLOB="prover/circuits/8d079211715200ff06c5109639245502bfe94aa869908d31176aae4016182121"
if [[ ! -f "$CIRCUIT_BLOB" ]]; then
  echo "Missing $CIRCUIT_BLOB. Run scripts/bootstrap.sh first." >&2
  exit 1
fi
blob_sha=$(shasum -a 256 "$CIRCUIT_BLOB" | cut -d' ' -f1)
pinned_sha=$(grep -o '"[0-9a-f]\{64\}"' prover/wasm/prover_wasm.cc | head -1 | tr -d '"')
if [[ "$blob_sha" != "$pinned_sha" ]]; then
  echo "Circuit digest mismatch." >&2
  echo "  shipped blob : $blob_sha" >&2
  echo "  pinned in .cc: $pinned_sha" >&2
  echo "Update kExpectedCircuitSha256 in prover/wasm/prover_wasm.cc." >&2
  exit 1
fi
echo "    $blob_sha"

mkdir -p "$OUT_DIR" "$OBJ_DIR"

# -O3 everywhere. The prover is compute-bound, so optimisation level dominates
# wall-clock far more than it affects binary size here.
#
# -msimd128 enables WebAssembly SIMD, supported by every current browser.
# Measured worth keeping: 6.25 s -> 5.06 s to prove (three runs each), and it
# also shrinks the module from 423955 to 405302 bytes.
#
# Single-dash default so SIMD_FLAG= (explicitly empty) really disables it; with
# :- an empty value would silently fall back to the default and quietly turn a
# no-SIMD A/B run back into a SIMD build.
SIMD_FLAG="${SIMD_FLAG--msimd128}"
CFLAGS_COMMON=(-O3 ${SIMD_FLAG})

# Proving grows the wasm heap to ~200 MB: a 130 MB scratch buffer for the circuit
# (Longfellow sizes it to kCircuitSizeMax, not the actual 94 MB) plus the prover's
# working set.
#
# Deliberately NOT preallocated. Reserving 448 MB up front measured identically
# to 64 MB (6.31 s vs 6.22 s across three runs each), so it buys no speed, makes
# page load likelier to fail on a memory-constrained device, and ends up holding
# 470 MB where growth peaks at 200 MB. Let it grow.
INITIAL_MEMORY="${INITIAL_MEMORY:-64MB}"

step "Compiling zstd (decompress only)"
# The browser only ever decompresses: the circuit ships pre-compressed, and
# circuit generation (the sole compressor caller) is deliberately excluded from
# this build. ZSTD_DISABLE_ASM is required because the x86-64 huf_decompress
# assembly cannot target wasm.
ZSTD_SRCS=(
  "$ZSTD_ROOT"/lib/common/debug.c
  "$ZSTD_ROOT"/lib/common/entropy_common.c
  "$ZSTD_ROOT"/lib/common/error_private.c
  "$ZSTD_ROOT"/lib/common/fse_decompress.c
  "$ZSTD_ROOT"/lib/common/xxhash.c
  "$ZSTD_ROOT"/lib/common/zstd_common.c
  "$ZSTD_ROOT"/lib/decompress/huf_decompress.c
  "$ZSTD_ROOT"/lib/decompress/zstd_ddict.c
  "$ZSTD_ROOT"/lib/decompress/zstd_decompress.c
  "$ZSTD_ROOT"/lib/decompress/zstd_decompress_block.c
)
zstd_objs=()
for src in "${ZSTD_SRCS[@]}"; do
  obj="$OBJ_DIR/zstd_$(basename "${src%.c}").o"
  emcc "${CFLAGS_COMMON[@]}" -DZSTD_DISABLE_ASM=1 \
    -I"$ZSTD_ROOT/lib" -I"$ZSTD_ROOT/lib/common" \
    -c "$src" -o "$obj"
  zstd_objs+=("$obj")
done
echo "    ${#zstd_objs[@]} objects"

step "Compiling Longfellow (portable crypto, no OpenSSL)"
# mdoc_generate_circuit.cc is intentionally absent: it is the only compressor
# caller, and generating circuits in a browser tab is not a thing we want to do.
LF_SRCS=(
  lib/circuits/mdoc/mdoc_zk.cc
  lib/circuits/mdoc/mdoc_decompress.cc
  lib/circuits/mdoc/mdoc_circuit_id.cc
  lib/circuits/mdoc/zk_spec.cc
  lib/circuits/sha/flatsha256_witness.cc
  lib/circuits/sha/sha256_constants.cc
  lib/ec/p256.cc
  lib/ec/p256k1.cc
  lib/algebra/crt.cc
  lib/algebra/nat.cc
  lib/util/crypto.cc
  lib/util/log.cc
)
lf_objs=()
for src in "${LF_SRCS[@]}"; do
  obj="$OBJ_DIR/lf_$(basename "${src%.cc}").o"
  emcc "${CFLAGS_COMMON[@]}" -std=c++17 -DLONGFELLOW_PORTABLE_CRYPTO=1 \
    -I"$LF_ROOT/lib" -I"$ZSTD_ROOT/lib" \
    -c "$LF_ROOT/$src" -o "$obj"
  lf_objs+=("$obj")
done
echo "    ${#lf_objs[@]} objects"

step "Compiling and linking the wasm module"
# ALLOW_MEMORY_GROWTH because proving peaks around 350 MB natively, most of it
# the 94 MB decompressed circuit plus prover working set.
# No pthreads: Longfellow's core is single-threaded, which means we avoid
# SharedArrayBuffer and therefore avoid having to serve COOP/COEP headers. That
# matters because those headers would break the cross-origin identicon images.
# em++ rather than emcc: the link needs libc++, and emcc would leave operator
# new/delete undefined.
em++ "${CFLAGS_COMMON[@]}" -std=c++17 -DLONGFELLOW_PORTABLE_CRYPTO=1 \
  -I"$LF_ROOT/lib" -I"$ZSTD_ROOT/lib" \
  prover/wasm/prover_wasm.cc "${lf_objs[@]}" "${zstd_objs[@]}" \
  -o "$OUT_DIR/veridict_prover.js" \
  -s WASM=1 \
  -s MODULARIZE=1 \
  -s EXPORT_NAME=createVeridictProver \
  -s ALLOW_MEMORY_GROWTH=1 \
  -s INITIAL_MEMORY="$INITIAL_MEMORY" \
  -s STACK_SIZE=8MB \
  -s EXPORTED_FUNCTIONS='["_veridict_prove","_veridict_free","_veridict_check_circuit","_veridict_check_circuit_id","_veridict_expected_circuit_hash","_veridict_expected_circuit_sha256","_veridict_num_attributes","_malloc","_free"]' \
  -s EXPORTED_RUNTIME_METHODS='["ccall","cwrap","HEAPU8","getValue","setValue","UTF8ToString","lengthBytesUTF8","stringToUTF8"]' \
  -s ENVIRONMENT=web,worker,node \
  -s EXIT_RUNTIME=0

step "Done"
ls -la "$OUT_DIR"
