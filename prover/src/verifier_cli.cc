// Anonymous Review Verifier — wraps Longfellow's run_mdoc_verifier.
//
// Reads a proof produced by prover_cli and verifies it against the public
// inputs. The verifier never sees the MDOC — only the claim, the transcript,
// the issuer pubkey, and the proof.
//
// Exit 0 = valid proof; non-zero = invalid (or error).

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
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

std::vector<uint8_t> hex_decode(const std::string& hex) {
  std::string h = hex;
  if (h.rfind("0x", 0) == 0) h = h.substr(2);
  std::vector<uint8_t> out(h.size() / 2);
  for (size_t i = 0; i < out.size(); ++i) {
    out[i] = static_cast<uint8_t>(std::stoi(h.substr(2 * i, 2), nullptr, 16));
  }
  return out;
}

RequestedAttribute parse_claim(const std::string& spec) {
  size_t p1 = spec.find(':');
  size_t p2 = spec.find(':', p1 + 1);
  std::string ns = spec.substr(0, p1);
  std::string id = spec.substr(p1 + 1, p2 - p1 - 1);
  std::vector<uint8_t> val = hex_decode(spec.substr(p2 + 1));

  RequestedAttribute r{};
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

}  // namespace

int main(int argc, char** argv) {
  std::string proof_path = get_arg(argc, argv, "--proof");
  std::string pkx = get_arg(argc, argv, "--pkx");
  std::string pky = get_arg(argc, argv, "--pky");
  std::string transcript_hex = get_arg(argc, argv, "--transcript");
  std::string claim_spec = get_arg(argc, argv, "--claim");
  std::string now = get_arg(argc, argv, "--now");
  std::string doc_type = get_arg(argc, argv, "--doctype");

  auto proof = read_file(proof_path);
  auto transcript = hex_decode(transcript_hex);
  RequestedAttribute attr = parse_claim(claim_spec);

  uint8_t* circuit = nullptr;
  size_t circuit_len = 0;
  if (generate_circuit(&kZkSpecs[0], &circuit, &circuit_len)
      != CIRCUIT_GENERATION_SUCCESS) {
    std::cerr << "circuit generation failed\n";
    return 3;
  }

  auto rc = run_mdoc_verifier(
      circuit, circuit_len,
      pkx.c_str(), pky.c_str(),
      transcript.data(), transcript.size(),
      &attr, /*attrs_len=*/1,
      now.c_str(),
      proof.data(), proof.size(),
      doc_type.c_str(),
      &kZkSpecs[0]);

  std::free(circuit);

  if (rc != MDOC_VERIFIER_SUCCESS) {
    std::cerr << "verification failed: " << rc << "\n";
    return static_cast<int>(rc);
  }
  std::cout << "OK\n";
  return 0;
}
