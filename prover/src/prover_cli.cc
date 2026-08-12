// Anonymous Review Prover — wraps Longfellow's run_mdoc_prover.
//
// Inputs (all paths or hex strings):
//   --mdoc <path>          : raw MDOC bytes (from the issuer)
//   --pkx <hex>            : issuer P-256 pubkey x coordinate (0x-prefixed)
//   --pky <hex>            : issuer P-256 pubkey y coordinate
//   --transcript <hex>     : challenge bytes (PR id + commit hash, hex-encoded)
//   --claim <ns>:<id>:<hex>: attribute namespace, id, and CBOR-encoded value
//                            e.g. "org.example.reviewer:role:6a6d61696e7461696e6572"
//                            (CBOR text(10) "maintainer")
//   --now <YYYY-MM-DDTHH:MM:SSZ> : current time (must satisfy validity window)
//   --out <path>           : write the ZK proof here
//   --circuit <path>       : optional cached circuit blob (see circuit_tool).
//                            Omitting it regenerates the circuit, which costs
//                            ~15 s and should never happen in a request path.
//
// Exits 0 on success, non-zero with an MdocProverErrorCode on failure.

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "circuits/mdoc/mdoc_zk.h"

namespace {

std::vector<uint8_t> read_file(const std::string& path) {
  std::ifstream f(path, std::ios::binary);
  if (!f) {
    std::cerr << "cannot open: " << path << "\n";
    std::exit(2);
  }
  return {std::istreambuf_iterator<char>(f), {}};
}

void write_file(const std::string& path, const uint8_t* data, size_t len) {
  std::ofstream f(path, std::ios::binary);
  f.write(reinterpret_cast<const char*>(data), len);
}

std::vector<uint8_t> hex_decode(const std::string& hex) {
  std::string h = hex;
  if (h.rfind("0x", 0) == 0) h = h.substr(2);
  if (h.size() % 2 != 0) {
    std::cerr << "odd hex length\n";
    std::exit(2);
  }
  std::vector<uint8_t> out(h.size() / 2);
  for (size_t i = 0; i < out.size(); ++i) {
    out[i] = static_cast<uint8_t>(std::stoi(h.substr(2 * i, 2), nullptr, 16));
  }
  return out;
}

RequestedAttribute parse_claim(const std::string& spec) {
  // format: "<namespace>:<id>:<cbor_value_hex>"
  size_t p1 = spec.find(':');
  size_t p2 = spec.find(':', p1 + 1);
  if (p1 == std::string::npos || p2 == std::string::npos) {
    std::cerr << "claim must be ns:id:hex\n";
    std::exit(2);
  }
  std::string ns = spec.substr(0, p1);
  std::string id = spec.substr(p1 + 1, p2 - p1 - 1);
  std::vector<uint8_t> val = hex_decode(spec.substr(p2 + 1));

  RequestedAttribute r{};
  if (ns.size() > sizeof(r.namespace_id) || id.size() > sizeof(r.id) ||
      val.size() > sizeof(r.cbor_value)) {
    std::cerr << "claim field too long for fixed buffers\n";
    std::exit(2);
  }
  std::memcpy(r.namespace_id, ns.data(), ns.size());
  std::memcpy(r.id, id.data(), id.size());
  std::memcpy(r.cbor_value, val.data(), val.size());
  r.namespace_len = ns.size();
  r.id_len = id.size();
  r.cbor_value_len = val.size();
  return r;
}

std::string get_arg(int argc, char** argv, const std::string& flag) {
  for (int i = 1; i + 1 < argc; ++i) {
    if (flag == argv[i]) return argv[i + 1];
  }
  std::cerr << "missing required flag: " << flag << "\n";
  std::exit(2);
}

std::string get_opt_arg(int argc, char** argv, const std::string& flag) {
  for (int i = 1; i + 1 < argc; ++i) {
    if (flag == argv[i]) return argv[i + 1];
  }
  return "";
}

}  // namespace

int main(int argc, char** argv) {
  std::string mdoc_path = get_arg(argc, argv, "--mdoc");
  std::string pkx = get_arg(argc, argv, "--pkx");
  std::string pky = get_arg(argc, argv, "--pky");
  std::string transcript_hex = get_arg(argc, argv, "--transcript");
  std::string claim_spec = get_arg(argc, argv, "--claim");
  std::string now = get_arg(argc, argv, "--now");
  std::string out_path = get_arg(argc, argv, "--out");

  auto mdoc = read_file(mdoc_path);
  auto transcript = hex_decode(transcript_hex);
  RequestedAttribute attr = parse_claim(claim_spec);

  // The circuit is deterministic per ZK spec and takes ~15 s to generate, so
  // prefer a cached blob (see circuit_tool). Generating inline is the fallback
  // and should not happen in a request path. kZkSpecs[0] = 1-attribute circuit.
  std::string circuit_path = get_opt_arg(argc, argv, "--circuit");
  std::vector<uint8_t> circuit_blob;
  uint8_t* circuit = nullptr;
  size_t circuit_len = 0;
  bool circuit_owned = false;
  if (!circuit_path.empty()) {
    circuit_blob = read_file(circuit_path);
    circuit = circuit_blob.data();
    circuit_len = circuit_blob.size();
  } else {
    auto gen = generate_circuit(&kZkSpecs[0], &circuit, &circuit_len);
    if (gen != CIRCUIT_GENERATION_SUCCESS) {
      std::cerr << "circuit generation failed: " << gen << "\n";
      return 3;
    }
    circuit_owned = true;
  }

  uint8_t* proof = nullptr;
  size_t proof_len = 0;
  auto rc = run_mdoc_prover(
      circuit, circuit_len,
      mdoc.data(), mdoc.size(),
      pkx.c_str(), pky.c_str(),
      transcript.data(), transcript.size(),
      &attr, /*attrs_len=*/1,
      now.c_str(),
      &proof, &proof_len,
      &kZkSpecs[0]);

  if (circuit_owned) std::free(circuit);

  if (rc != MDOC_PROVER_SUCCESS) {
    std::cerr << "prover failed: " << rc << "\n";
    return static_cast<int>(rc);
  }

  write_file(out_path, proof, proof_len);
  std::free(proof);
  std::cout << "wrote " << proof_len << " bytes to " << out_path << "\n";
  return 0;
}
