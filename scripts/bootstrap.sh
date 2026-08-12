#!/usr/bin/env bash
# One-shot bootstrap: clone & patch Longfellow, build prover/verifier,
# install Python deps, run MDOC format validation. Run from project root.
#
# Run with:   ./scripts/bootstrap.sh
# Re-run is safe (idempotent for clone/patch/build steps).

set -euo pipefail
cd "$(dirname "$0")/.."

LF_ROOT="${LF_ROOT:-../longfellow-zk}"

step() { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }

step "[0/7] Install system dependencies"
if [[ "$(uname)" == "Darwin" ]]; then
  if ! command -v brew >/dev/null; then
    echo "    Homebrew not found — install from https://brew.sh first"; exit 1
  fi
  brew install googletest google-benchmark zstd openssl@3 cmake
elif command -v apt-get >/dev/null; then
  sudo apt-get update
  sudo apt-get install -y clang cmake libssl-dev libzstd-dev libgtest-dev \
       libbenchmark-dev zlib1g-dev
elif command -v yum >/dev/null; then
  sudo yum install -y clang libzstd-devel openssl-devel git cmake \
       google-benchmark-devel gtest-devel
else
  echo "    Unknown package manager — install: clang, cmake, openssl, zstd,"
  echo "    googletest, googlebenchmark"
  exit 1
fi

step "[1/7] Clone Longfellow (if needed)"
if [[ ! -d "$LF_ROOT" ]]; then
  git clone https://github.com/google/longfellow-zk "$LF_ROOT"
fi

step "[2/7] Apply patches (if not already applied)"
pushd "$LF_ROOT" > /dev/null
if grep -q kReviewerNamespace lib/circuits/mdoc/mdoc_attribute_ids.h 2>/dev/null; then
  echo "    reviewer-namespace: already applied"
else
  git apply "$OLDPWD/patches/add-reviewer-namespace.patch"
  echo "    reviewer-namespace: applied"
fi
# Adds a dependency-free SHA-256 / AES-256-ECB / RNG shim behind
# -DLONGFELLOW_PORTABLE_CRYPTO=1. Inert for the native build, which keeps using
# OpenSSL; required for the WebAssembly build.
if grep -q LONGFELLOW_PORTABLE_CRYPTO lib/util/crypto.h 2>/dev/null; then
  echo "    portable-crypto: already applied"
else
  git apply "$OLDPWD/patches/portable-crypto.patch"
  echo "    portable-crypto: applied"
fi
popd > /dev/null

step "[3/7] Build Longfellow (Release)"
CMAKE_EXTRA=()
if [[ "$(uname)" == "Darwin" ]]; then
  BREW_PREFIX="$(brew --prefix)"
  CMAKE_EXTRA+=(
    "-DCMAKE_PREFIX_PATH=${BREW_PREFIX}/opt/google-benchmark;${BREW_PREFIX}/opt/googletest;${BREW_PREFIX}/opt/zstd;${BREW_PREFIX}/opt/openssl@3"
  )
fi
if [[ ! -f "$LF_ROOT/build/circuits/mdoc/libmdoc.a" ]]; then
  pushd "$LF_ROOT" > /dev/null
  CXX=clang++ cmake -DCMAKE_BUILD_TYPE=Release -S lib -B build "${CMAKE_EXTRA[@]}"
  cmake --build build -j"$(getconf _NPROCESSORS_ONLN || echo 4)"
  popd > /dev/null
else
  echo "    already built"
fi

step "[4/7] Build our prover_cli / verifier_cli / circuit_tool"
cmake -DLONGFELLOW_ROOT="$(realpath "$LF_ROOT")" -S prover -B prover/build
cmake --build prover/build -j"$(getconf _NPROCESSORS_ONLN || echo 4)"

step "[5/7] Verify the cached circuit blob"
# Circuit generation is deterministic per ZK spec and costs ~15 s at 1.4 GB peak
# RSS, so the blob is committed and loaded at runtime instead. It is byte-identical
# to the one Longfellow ships; this step re-checks that rather than assuming it.
CIRCUIT_FILE="prover/circuits/8d079211715200ff06c5109639245502bfe94aa869908d31176aae4016182121"
if [[ -f "$CIRCUIT_FILE" ]]; then
  ./prover/build/circuit_tool --check "$CIRCUIT_FILE" --spec 0
else
  echo "    missing, generating (~15 s)"
  mkdir -p prover/circuits
  ./prover/build/circuit_tool --generate --spec 0 --out "$CIRCUIT_FILE"
fi

step "[6/7] Install Python deps (issuer + backend)"
python3 -m pip install -q -r issuer/requirements.txt
python3 -m pip install -q -r backend/requirements.txt

step "[7/7] Run MDOC format validation"
LF_ROOT="$LF_ROOT" ./scripts/validate_mdoc_format.sh

echo
echo "Bootstrap complete. Next:"
echo "  Terminal A:  DEV_MODE=1 python issuer/server.py"
echo "  Terminal B:  python backend/main.py"
echo "  Terminal C:  ./scripts/demo.sh"
