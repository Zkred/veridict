// WebAssembly entry point for the Veridict prover.
//
// This is the browser-side half of the trust-model fix: the reviewer's device
// key and MDOC credential never leave the browser, so the issuer cannot forge
// an approval on their behalf. The issuer becomes a pure attestation service.
//
// The circuit is NOT generated here. It is fetched as a static asset (316 KB
// compressed, content-addressed by circuit hash) and handed in by the caller.
// Generating it instead would cost ~15 s and 1.4 GB of memory, which is not
// something to do in a tab.
//
// Exposed as a flat C ABI over buffers, which is the shape emscripten's
// cwrap/HEAPU8 access maps onto most cleanly. All buffers are caller-allocated
// except the proof, which is malloc'd here and must be released with
// veridict_free.

#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <string>

#include "circuits/mdoc/mdoc_zk.h"
#include "util/crypto.h"

#ifdef __EMSCRIPTEN__
#include <emscripten/emscripten.h>
#else
#define EMSCRIPTEN_KEEPALIVE
#endif

namespace {

// Mirrors the error space of MdocProverErrorCode without colliding with it, so
// JS can distinguish "we rejected the inputs" from "the prover failed".
enum VeridictError {
  kVeridictOk = 0,
  kVeridictBadArgs = -1,
  kVeridictClaimTooLong = -2,
  kVeridictCircuitMismatch = -3,
};

// SHA-256 of the compressed circuit blob this build expects, i.e. of
// prover/circuits/<circuit_id>. Checked against the shipped file at build time
// by prover/wasm/build.sh, so the two cannot drift apart silently.
//
// Note this is the hash of the *compressed bytes*, which is not the same thing
// as the circuit_id in kZkSpecs (that is computed from the parsed circuit).
// Hashing the blob is what makes the check cheap: deriving the circuit_id
// instead costs a full decompress and parse, measured at 3.5 s in wasm, which
// duplicates work run_mdoc_prover does anyway.
constexpr char kExpectedCircuitSha256[] =
    "9016d173d8a579a104591b85826798bfbb03eafa7b376ad18c5344eab3a92769";

void ToHex(const uint8_t* in, size_t n, char* out) {
  static const char kHex[] = "0123456789abcdef";
  for (size_t i = 0; i < n; ++i) {
    out[2 * i] = kHex[in[i] >> 4];
    out[2 * i + 1] = kHex[in[i] & 0x0f];
  }
  out[2 * n] = '\0';
}

}  // namespace

extern "C" {

// Returns the circuit hash this build expects, as a 64-char hex string. The
// caller should use it to pick which circuit asset to fetch.
EMSCRIPTEN_KEEPALIVE
const char* veridict_expected_circuit_hash() {
  return kZkSpecs[0].circuit_hash;
}

EMSCRIPTEN_KEEPALIVE
size_t veridict_num_attributes() { return kZkSpecs[0].num_attributes; }

EMSCRIPTEN_KEEPALIVE
const char* veridict_expected_circuit_sha256() {
  return kExpectedCircuitSha256;
}

// Fail-fast integrity check on a circuit blob fetched over the network, by
// SHA-256 against the pinned digest above. Returns 1 on match, 0 otherwise.
//
// This is a UX guard, not a security boundary. A wrong circuit cannot produce an
// accepted approval regardless: the authoritative verifier runs server-side, and
// a proof against the wrong circuit fails there. The point is to fail in
// milliseconds with a clear error instead of after eight seconds of proving.
EMSCRIPTEN_KEEPALIVE
int veridict_check_circuit(const uint8_t* circuit, size_t circuit_len) {
  if (circuit == nullptr || circuit_len == 0) return 0;
  uint8_t digest[proofs::kSHA256DigestSize];
  proofs::SHA256 sha;
  sha.Update(circuit, circuit_len);
  sha.DigestData(digest);

  char hex[2 * proofs::kSHA256DigestSize + 1];
  ToHex(digest, sizeof(digest), hex);
  return std::strcmp(hex, kExpectedCircuitSha256) == 0 ? 1 : 0;
}

// The circuit_id-based check: stronger, in that it validates the parsed circuit
// rather than the bytes, but it costs a full decompress and parse (~3.5 s in
// wasm). Exposed for tooling and tests; the browser path uses the hash check.
EMSCRIPTEN_KEEPALIVE
int veridict_check_circuit_id(const uint8_t* circuit, size_t circuit_len) {
  if (circuit == nullptr || circuit_len == 0) return 0;
  uint8_t id[32];
  if (circuit_id(id, circuit, circuit_len, &kZkSpecs[0]) != 1) return 0;
  char hex[65];
  ToHex(id, sizeof(id), hex);
  return std::strcmp(hex, kZkSpecs[0].circuit_hash) == 0 ? 1 : 0;
}

// Generates a ZK proof that the holder of `mdoc` has the claimed attribute.
// Writes a malloc'd proof to *out_proof and its length to *out_len.
// Returns kVeridictOk (0) on success, a VeridictError on bad input, or the
// MdocProverErrorCode from the library on a proving failure.
EMSCRIPTEN_KEEPALIVE
int veridict_prove(const uint8_t* circuit, size_t circuit_len,
                   const uint8_t* mdoc, size_t mdoc_len,
                   const char* pkx, const char* pky,
                   const uint8_t* transcript, size_t transcript_len,
                   const char* claim_ns, const char* claim_id,
                   const uint8_t* claim_cbor, size_t claim_cbor_len,
                   const char* now, uint8_t** out_proof, size_t* out_len) {
  if (circuit == nullptr || mdoc == nullptr || pkx == nullptr ||
      pky == nullptr || transcript == nullptr || claim_ns == nullptr ||
      claim_id == nullptr || claim_cbor == nullptr || now == nullptr ||
      out_proof == nullptr || out_len == nullptr) {
    return kVeridictBadArgs;
  }

  RequestedAttribute attr{};
  size_t ns_len = std::strlen(claim_ns);
  size_t id_len = std::strlen(claim_id);
  if (ns_len > sizeof(attr.namespace_id) || id_len > sizeof(attr.id) ||
      claim_cbor_len > sizeof(attr.cbor_value)) {
    return kVeridictClaimTooLong;
  }
  std::memcpy(attr.namespace_id, claim_ns, ns_len);
  std::memcpy(attr.id, claim_id, id_len);
  std::memcpy(attr.cbor_value, claim_cbor, claim_cbor_len);
  attr.namespace_len = ns_len;
  attr.id_len = id_len;
  attr.cbor_value_len = claim_cbor_len;

  if (!veridict_check_circuit(circuit, circuit_len)) {
    return kVeridictCircuitMismatch;
  }

  uint8_t* proof = nullptr;
  size_t proof_len = 0;
  MdocProverErrorCode rc =
      run_mdoc_prover(circuit, circuit_len, mdoc, mdoc_len, pkx, pky,
                      transcript, transcript_len, &attr, /*attrs_len=*/1, now,
                      &proof, &proof_len, &kZkSpecs[0]);
  if (rc != MDOC_PROVER_SUCCESS) {
    if (proof != nullptr) std::free(proof);
    return static_cast<int>(rc);
  }

  *out_proof = proof;
  *out_len = proof_len;
  return kVeridictOk;
}

// Verifies a proof. Returns kVeridictOk (0) if the proof is valid, a
// VeridictError for bad input, or the MdocVerifierErrorCode from the library.
//
// Verification must stay server-authoritative: a browser that verified its own
// proof would be marking its own homework. This export exists so the *server*
// can run the verifier as WebAssembly instead of as a native binary, which is
// what makes a deployment without compiled artifacts possible. Same module, two
// consumers, one toolchain.
EMSCRIPTEN_KEEPALIVE
int veridict_verify(const uint8_t* circuit, size_t circuit_len,
                    const uint8_t* proof, size_t proof_len,
                    const char* pkx, const char* pky,
                    const uint8_t* transcript, size_t transcript_len,
                    const char* claim_ns, const char* claim_id,
                    const uint8_t* claim_cbor, size_t claim_cbor_len,
                    const char* now, const char* doc_type) {
  if (circuit == nullptr || proof == nullptr || pkx == nullptr ||
      pky == nullptr || transcript == nullptr || claim_ns == nullptr ||
      claim_id == nullptr || claim_cbor == nullptr || now == nullptr ||
      doc_type == nullptr) {
    return kVeridictBadArgs;
  }

  RequestedAttribute attr{};
  size_t ns_len = std::strlen(claim_ns);
  size_t id_len = std::strlen(claim_id);
  if (ns_len > sizeof(attr.namespace_id) || id_len > sizeof(attr.id) ||
      claim_cbor_len > sizeof(attr.cbor_value)) {
    return kVeridictClaimTooLong;
  }
  std::memcpy(attr.namespace_id, claim_ns, ns_len);
  std::memcpy(attr.id, claim_id, id_len);
  std::memcpy(attr.cbor_value, claim_cbor, claim_cbor_len);
  attr.namespace_len = ns_len;
  attr.id_len = id_len;
  attr.cbor_value_len = claim_cbor_len;

  if (!veridict_check_circuit(circuit, circuit_len)) {
    return kVeridictCircuitMismatch;
  }

  return static_cast<int>(run_mdoc_verifier(
      circuit, circuit_len, pkx, pky, transcript, transcript_len, &attr,
      /*attrs_len=*/1, now, proof, proof_len, doc_type, &kZkSpecs[0]));
}

EMSCRIPTEN_KEEPALIVE
void veridict_free(uint8_t* p) { std::free(p); }

}  // extern "C"
