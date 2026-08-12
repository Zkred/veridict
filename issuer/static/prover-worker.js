// Web Worker that runs the Longfellow prover in WebAssembly.
//
// Proving takes ~5 s and the wasm call is synchronous, so it has to happen off
// the main thread or the tab freezes and the progress overlay never paints.
//
// Protocol:
//   in : {type: "prove", circuitUrl, mdoc, deviceTbs, sigOffset, signature,
//         pkx, pky, transcriptHex, claimNs, claimId, claimCborHex, now}
//   out: {type: "progress", step, pct} | {type: "done", proof, ms}
//        | {type: "error", message}

importScripts("/wasm/veridict_prover.js");

let modulePromise = null;

function loadModule() {
  // Cached: instantiating compiles the wasm, and a reviewer may approve more
  // than one PR per page session.
  //
  // locateFile is required. Emscripten resolves the .wasm relative to the
  // importing script's own URL, which here is /js/prover-worker.js, so without
  // this it fetches /js/veridict_prover.wasm and instantiation fails on a 404
  // body instead of the module.
  if (!modulePromise) {
    modulePromise = createVeridictProver({
      locateFile: (path) => `/wasm/${path}`,
    });
  }
  return modulePromise;
}

function progress(step, pct) {
  self.postMessage({ type: "progress", step, pct });
}

function hexToBytes(hex) {
  const clean = hex.startsWith("0x") ? hex.slice(2) : hex;
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(clean.substr(2 * i, 2), 16);
  }
  return out;
}

// Copies bytes into the wasm heap. Callers must free what they allocate.
function allocBytes(M, bytes) {
  const ptr = M._malloc(bytes.length);
  if (!ptr) throw new Error("wasm malloc failed");
  M.HEAPU8.set(bytes, ptr);
  return ptr;
}

function allocString(M, str) {
  const len = M.lengthBytesUTF8(str) + 1;
  const ptr = M._malloc(len);
  if (!ptr) throw new Error("wasm malloc failed");
  M.stringToUTF8(str, ptr, len);
  return ptr;
}

// Maps the C error codes in prover_wasm.cc onto something a reviewer can act on.
function describeError(rc) {
  switch (rc) {
    case -1: return "prover rejected the inputs (bad arguments)";
    case -2: return "claim value too long for the credential format";
    case -3: return "circuit asset did not match the expected hash";
    default: return `prover failed with code ${rc}`;
  }
}

async function prove(msg) {
  progress("Loading prover module", 10);
  const M = await loadModule();

  progress("Fetching ZK circuit", 20);
  // Immutably cached and content-addressed by circuit hash, so this is a network
  // round trip only on the reviewer's first proof.
  const resp = await fetch(msg.circuitUrl, { cache: "force-cache" });
  if (!resp.ok) throw new Error(`circuit fetch failed: HTTP ${resp.status}`);
  const circuit = new Uint8Array(await resp.arrayBuffer());

  progress("Checking circuit integrity", 25);
  const ptrs = [];
  try {
    const circuitPtr = allocBytes(M, circuit);
    ptrs.push(circuitPtr);
    if (M._veridict_check_circuit(circuitPtr, circuit.length) !== 1) {
      const want = M.UTF8ToString(M._veridict_expected_circuit_sha256());
      throw new Error(`circuit asset failed its integrity check (expected ${want})`);
    }

    // Splice the device signature the main thread produced into the credential.
    // The issuer left exactly 64 zero bytes at sigOffset for it.
    const mdoc = new Uint8Array(msg.mdoc);
    const signature = new Uint8Array(msg.signature);
    if (signature.length !== 64) {
      throw new Error(`expected a 64-byte device signature, got ${signature.length}`);
    }
    mdoc.set(signature, msg.sigOffset);

    progress("Generating proof witness", 35);
    const mdocPtr = allocBytes(M, mdoc);
    const transcript = hexToBytes(msg.transcriptHex);
    const transcriptPtr = allocBytes(M, transcript);
    const claimCbor = hexToBytes(msg.claimCborHex);
    const claimPtr = allocBytes(M, claimCbor);
    const pkxPtr = allocString(M, msg.pkx);
    const pkyPtr = allocString(M, msg.pky);
    const nsPtr = allocString(M, msg.claimNs);
    const idPtr = allocString(M, msg.claimId);
    const nowPtr = allocString(M, msg.now);
    const outProofPtr = M._malloc(4); // wasm32: pointer and size_t are 4 bytes
    const outLenPtr = M._malloc(4);
    ptrs.push(mdocPtr, transcriptPtr, claimPtr, pkxPtr, pkyPtr, nsPtr, idPtr,
              nowPtr, outProofPtr, outLenPtr);

    progress("Proving in WebAssembly", 45);
    const started = Date.now();
    const rc = M._veridict_prove(
      circuitPtr, circuit.length,
      mdocPtr, mdoc.length,
      pkxPtr, pkyPtr,
      transcriptPtr, transcript.length,
      nsPtr, idPtr,
      claimPtr, claimCbor.length,
      nowPtr,
      outProofPtr, outLenPtr,
    );
    const ms = Date.now() - started;
    if (rc !== 0) throw new Error(describeError(rc));

    const proofPtr = M.getValue(outProofPtr, "i32");
    const proofLen = M.getValue(outLenPtr, "i32");
    if (!proofPtr || proofLen <= 0) throw new Error("prover returned an empty proof");

    // Copy out before freeing: HEAPU8 is a view over wasm memory.
    const proof = new Uint8Array(M.HEAPU8.subarray(proofPtr, proofPtr + proofLen));
    M._veridict_free(proofPtr);

    progress("Submitting proof", 90);
    self.postMessage({ type: "done", proof, ms }, [proof.buffer]);
  } finally {
    for (const p of ptrs) M._free(p);
  }
}

self.onmessage = (e) => {
  if (e.data && e.data.type === "prove") {
    prove(e.data).catch((err) => {
      self.postMessage({ type: "error", message: err.message || String(err) });
    });
  }
};
