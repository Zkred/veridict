// Runs the WebAssembly prover outside a browser, so the wasm build can be
// tested in CI without a headless Chrome. The proof it emits is byte-compatible
// with the native prover's, so the native verifier_cli is the oracle:
//
//   node prover/wasm/test/prove_node.cjs <out.proof>
//
// Exits non-zero on any failure. Prints timing and peak heap for comparison
// against the native numbers (0.47 s / 346 MB).

const fs = require("fs");
const path = require("path");

const REPO = path.resolve(__dirname, "../../..");
const CIRCUIT = path.join(
  REPO,
  "prover/circuits/8d079211715200ff06c5109639245502bfe94aa869908d31176aae4016182121",
);

function fail(msg) {
  console.error(`FAIL  ${msg}`);
  process.exit(1);
}

// Copies bytes into the wasm heap and returns the pointer.
function allocBytes(Module, bytes) {
  const ptr = Module._malloc(bytes.length);
  if (!ptr) fail("malloc returned null");
  Module.HEAPU8.set(bytes, ptr);
  return ptr;
}

// Copies a NUL-terminated UTF-8 string into the wasm heap.
function allocString(Module, str) {
  const len = Module.lengthBytesUTF8(str) + 1;
  const ptr = Module._malloc(len);
  if (!ptr) fail("malloc returned null");
  Module.stringToUTF8(str, ptr, len);
  return ptr;
}

async function main() {
  const outPath = process.argv[2];
  if (!outPath) fail("usage: prove_node.cjs <out.proof>");

  // Timed separately: module instantiation compiles the wasm and is a one-off
  // cost the browser pays once per page load, not once per proof. Longfellow's
  // own log timestamps are relative to logger init, so they fold this in and
  // read as if decompression were slow. It isn't.
  const tInit = Date.now();
  const createVeridictProver = require("../dist/veridict_prover.js");
  const Module = await createVeridictProver();
  const initMs = Date.now() - tInit;

  // The circuit hash is compiled into the module, so the caller always knows
  // which asset to fetch rather than having it configured separately.
  const expectedHash = Module.UTF8ToString(
    Module._veridict_expected_circuit_hash(),
  );
  console.log(`expected circuit : ${expectedHash}`);
  console.log(`attributes       : ${Module._veridict_num_attributes()}`);

  if (path.basename(CIRCUIT) !== expectedHash) {
    fail(`circuit asset ${path.basename(CIRCUIT)} != expected ${expectedHash}`);
  }

  const circuit = fs.readFileSync(CIRCUIT);
  const mdoc = fs.readFileSync(path.join(REPO, ".validate/ours.mdoc"));
  const transcript = fs.readFileSync(path.join(REPO, ".validate/ours.transcript"));
  const now = fs.readFileSync(path.join(REPO, ".validate/ours.now"), "utf8").trim();
  const pubkey = fs
    .readFileSync(path.join(REPO, ".validate/ours.pubkey"), "utf8")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  const [pkx, pky] = pubkey;

  // CBOR text(10) "maintainer", matching what the issuer mints.
  const claimCbor = Buffer.from("6a6d61696e7461696e6572", "hex");

  const circuitPtr = allocBytes(Module, circuit);

  // Check the blob before proving: a wrong circuit would otherwise surface as an
  // opaque prover error 300 MB later.
  const tCheck = Date.now();
  if (Module._veridict_check_circuit(circuitPtr, circuit.length) !== 1) {
    fail("veridict_check_circuit rejected the circuit blob");
  }
  console.log(`circuit check    : OK (${((Date.now() - tCheck) / 1000).toFixed(2)} s)`);

  const mdocPtr = allocBytes(Module, mdoc);
  const transcriptPtr = allocBytes(Module, transcript);
  const claimPtr = allocBytes(Module, claimCbor);
  const pkxPtr = allocString(Module, pkx);
  const pkyPtr = allocString(Module, pky);
  const nsPtr = allocString(Module, "org.example.reviewer");
  const idPtr = allocString(Module, "role");
  const nowPtr = allocString(Module, now);

  // wasm32: pointers and size_t are both 4 bytes.
  const outProofPtr = Module._malloc(4);
  const outLenPtr = Module._malloc(4);

  const started = Date.now();
  const rc = Module._veridict_prove(
    circuitPtr, circuit.length,
    mdocPtr, mdoc.length,
    pkxPtr, pkyPtr,
    transcriptPtr, transcript.length,
    nsPtr, idPtr,
    claimPtr, claimCbor.length,
    nowPtr,
    outProofPtr, outLenPtr,
  );
  const elapsedMs = Date.now() - started;

  if (rc !== 0) fail(`veridict_prove returned ${rc}`);

  const proofPtr = Module.getValue(outProofPtr, "i32");
  const proofLen = Module.getValue(outLenPtr, "i32");
  if (!proofPtr || proofLen <= 0) fail(`bad proof ptr/len: ${proofPtr}/${proofLen}`);

  const proof = Buffer.from(Module.HEAPU8.slice(proofPtr, proofPtr + proofLen));
  fs.writeFileSync(outPath, proof);

  Module._veridict_free(proofPtr);

  console.log(`module init      : ${(initMs / 1000).toFixed(2)} s (one-off per page load)`);
  console.log(`prove time       : ${(elapsedMs / 1000).toFixed(2)} s`);
  console.log(`proof size       : ${proofLen} bytes`);
  console.log(`wasm heap        : ${(Module.HEAPU8.length / 1e6).toFixed(0)} MB`);
  console.log(`wrote            : ${outPath}`);
}

main().catch((e) => fail(e.stack || String(e)));
