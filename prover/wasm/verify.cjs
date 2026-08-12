// Verifies a Longfellow ZK proof using the WebAssembly module.
//
// Drop-in replacement for prover/build/verifier_cli: same flags, same exit-code
// convention (0 = valid, non-zero = not), "OK" on stdout when valid. That lets
// the backend swap one for the other without changing its calling code.
//
// Why this exists: verification must be server-side to be authoritative, but the
// native verifier_cli is a compiled binary, which is the last thing standing
// between this project and a deployment target that cannot build C++. Running
// the same wasm module the browser uses removes that constraint.
//
//   node prover/wasm/verify.cjs --proof p.bin --circuit c.bin \
//     --pkx 0x.. --pky 0x.. --transcript <hex> \
//     --claim org.example.reviewer:role:6a6d.. --now 2026-01-01T00:00:00Z \
//     --doctype org.example.reviewer.v1

const fs = require("fs");
const path = require("path");

function arg(flag, required = true) {
  const i = process.argv.indexOf(flag);
  if (i < 0 || i + 1 >= process.argv.length) {
    if (required) {
      process.stderr.write(`missing required flag: ${flag}\n`);
      process.exit(2);
    }
    return null;
  }
  return process.argv[i + 1];
}

function hexToBytes(hex) {
  const clean = hex.startsWith("0x") ? hex.slice(2) : hex;
  if (clean.length % 2 !== 0) {
    process.stderr.write("odd hex length\n");
    process.exit(2);
  }
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(clean.substr(2 * i, 2), 16);
  }
  return out;
}

// "<namespace>:<id>:<cbor_value_hex>", matching verifier_cli's --claim format.
function parseClaim(spec) {
  const p1 = spec.indexOf(":");
  const p2 = spec.indexOf(":", p1 + 1);
  if (p1 < 0 || p2 < 0) {
    process.stderr.write("claim must be ns:id:hex\n");
    process.exit(2);
  }
  return {
    ns: spec.slice(0, p1),
    id: spec.slice(p1 + 1, p2),
    cbor: hexToBytes(spec.slice(p2 + 1)),
  };
}

function describeError(rc) {
  switch (rc) {
    case -1: return "bad arguments";
    case -2: return "claim value too long";
    case -3: return "circuit did not match the expected hash";
    default: return `verifier returned ${rc}`;
  }
}

async function main() {
  const proofPath = arg("--proof");
  const circuitPath = arg("--circuit");
  const pkx = arg("--pkx");
  const pky = arg("--pky");
  const transcriptHex = arg("--transcript");
  const claim = parseClaim(arg("--claim"));
  const now = arg("--now");
  const docType = arg("--doctype");

  const createVeridictProver = require(
    path.join(__dirname, "dist", "veridict_prover.js"),
  );
  const M = await createVeridictProver();

  const alloc = (bytes) => {
    const p = M._malloc(bytes.length);
    M.HEAPU8.set(bytes, p);
    return p;
  };
  const allocStr = (s) => {
    const len = M.lengthBytesUTF8(s) + 1;
    const p = M._malloc(len);
    M.stringToUTF8(s, p, len);
    return p;
  };

  const circuit = fs.readFileSync(circuitPath);
  const proof = fs.readFileSync(proofPath);
  const transcript = hexToBytes(transcriptHex);

  const rc = M._veridict_verify(
    alloc(circuit), circuit.length,
    alloc(proof), proof.length,
    allocStr(pkx), allocStr(pky),
    alloc(transcript), transcript.length,
    allocStr(claim.ns), allocStr(claim.id),
    alloc(claim.cbor), claim.cbor.length,
    allocStr(now), allocStr(docType),
  );

  if (rc !== 0) {
    process.stderr.write(`verification failed: ${describeError(rc)}\n`);
    process.exit(typeof rc === "number" && rc > 0 ? rc : 1);
  }
  process.stdout.write("OK\n");
}

main().catch((e) => {
  process.stderr.write(`${e.stack || e}\n`);
  process.exit(1);
});
