"""In-process WebAssembly proof verification, via wasmtime.

Why this exists
---------------
Verification must run server-side to be authoritative, and it used to mean
executing a compiled C++ binary. That is the one thing that cannot be assumed on
a serverless host: no compiler at build time, no guarantee of a particular
runtime being installed. Shelling out to `node` merely moves the assumption.

Running the wasm module directly from Python removes the assumption entirely.
The module is the same one the browser proves with, built by
prover/wasm/build.sh with -sSTANDALONE_WASM so it targets WASI instead of
emscripten's JavaScript glue. It needs five standard WASI calls plus one
emscripten memory-growth notification, which is a no-op here.

Trust note: the browser also carries a verify export, but a client verifying its
own proof establishes nothing. What matters is that the *server* verifies, which
is what this module does.
"""

from __future__ import annotations

import os
import threading

from wasmtime import (
    Engine,
    FuncType,
    Linker,
    Module,
    Store,
    ValType,
    WasiConfig,
)

# Mirrors the VeridictError enum in prover/wasm/prover_wasm.cc.
VERIDICT_OK = 0
_ERRORS = {
    -1: "bad arguments",
    -2: "claim value too long",
    -3: "circuit did not match the expected hash",
}


def describe(rc: int) -> str:
    return _ERRORS.get(rc, f"verifier returned {rc}")


class WasmVerifier:
    """Compiles the module once and instantiates per verification.

    Compilation is the expensive part, so the Engine and Module are shared. Each
    call gets a fresh Store and instance: the prover/verifier grows its heap to
    ~200 MB and does not free it back, so reusing an instance across requests
    would accumulate memory for no benefit.
    """

    def __init__(self, wasm_path: str):
        self.wasm_path = wasm_path
        self._engine = Engine()
        self._module = Module.from_file(self._engine, wasm_path)
        # Module compilation is not thread-safe to trigger concurrently in
        # wasmtime-py's binding layer; instantiation below is per-call anyway.
        self._lock = threading.Lock()

    def _instantiate(self) -> tuple[Store, dict]:
        store = Store(self._engine)

        # Longfellow logs progress to stderr; surface it like the CLI did.
        wasi = WasiConfig()
        wasi.inherit_stderr()
        store.set_wasi(wasi)

        linker = Linker(self._engine)
        linker.define_wasi()
        # emscripten emits this hook so JS can re-wrap its heap views after a
        # memory.grow. There are no views to re-wrap here.
        linker.define_func(
            "env",
            "emscripten_notify_memory_growth",
            FuncType([ValType.i32()], []),
            lambda _idx: None,
        )

        instance = linker.instantiate(store, self._module)
        exports = instance.exports(store)

        # Required. A standalone module built with --no-entry is a WASI
        # "reactor": the host must call _initialize to run C++ static
        # initialisers. Longfellow has global field objects (the P-256 base
        # field among them), so skipping this does not fail loudly — it leaves
        # them zeroed and verification rejects valid proofs with
        # MDOC_VERIFIER_INVALID_INPUT.
        initialize = exports.get("_initialize")
        if initialize is not None:
            initialize(store)

        return store, exports

    def verify(
        self,
        circuit: bytes,
        proof: bytes,
        pkx: str,
        pky: str,
        transcript: bytes,
        claim_ns: str,
        claim_id: str,
        claim_cbor: bytes,
        now: str,
        doc_type: str,
    ) -> int:
        """Returns 0 if the proof is valid, non-zero otherwise."""
        with self._lock:
            store, exports = self._instantiate()

        memory = exports["memory"]
        malloc = exports["malloc"]
        verify_fn = exports["veridict_verify"]

        def alloc_bytes(data: bytes) -> int:
            ptr = malloc(store, len(data))
            if not ptr:
                raise MemoryError("wasm malloc failed")
            memory.write(store, data, ptr)
            return ptr

        def alloc_str(text: str) -> int:
            return alloc_bytes(text.encode() + b"\x00")

        circuit_ptr = alloc_bytes(circuit)
        proof_ptr = alloc_bytes(proof)
        transcript_ptr = alloc_bytes(transcript)
        claim_ptr = alloc_bytes(claim_cbor)

        return verify_fn(
            store,
            circuit_ptr, len(circuit),
            proof_ptr, len(proof),
            alloc_str(pkx), alloc_str(pky),
            transcript_ptr, len(transcript),
            alloc_str(claim_ns), alloc_str(claim_id),
            claim_ptr, len(claim_cbor),
            alloc_str(now), alloc_str(doc_type),
        )

    def expected_circuit_sha256(self) -> str:
        """The circuit digest compiled into the module."""
        with self._lock:
            store, exports = self._instantiate()
        ptr = exports["veridict_expected_circuit_sha256"](store)
        memory = exports["memory"]
        raw = memory.read(store, ptr, ptr + 64)
        return bytes(raw).decode()


_verifier: WasmVerifier | None = None
_verifier_lock = threading.Lock()


def get_verifier(wasm_path: str) -> WasmVerifier | None:
    """Returns a process-wide verifier, or None if the module is missing."""
    global _verifier
    if not os.path.exists(wasm_path):
        return None
    with _verifier_lock:
        if _verifier is None or _verifier.wasm_path != wasm_path:
            _verifier = WasmVerifier(wasm_path)
    return _verifier
