// Circuit tool — generate, inspect, and validate Longfellow circuit blobs.
//
// Circuit generation is the slow part of proving (~8 s). It is also
// deterministic per ZK spec, so it belongs in a build step rather than in the
// request path. This tool produces the cached blob that prover_cli and
// verifier_cli consume via --circuit, and checks a blob against the expected
// circuit hash recorded in kZkSpecs.
//
//   circuit_tool --list
//   circuit_tool --generate [--spec N] --out <path>
//   circuit_tool --check <path> [--spec N]
//
// --spec indexes kZkSpecs (default 0 = 1-attribute, latest version).
// Exits 0 on success, non-zero on failure.

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <chrono>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "openssl/sha.h"

#include "circuits/mdoc/mdoc_zk.h"

namespace {

std::string to_hex(const uint8_t* data, size_t len) {
  static const char* kHex = "0123456789abcdef";
  std::string out;
  out.reserve(len * 2);
  for (size_t i = 0; i < len; ++i) {
    out.push_back(kHex[data[i] >> 4]);
    out.push_back(kHex[data[i] & 0x0f]);
  }
  return out;
}

std::string sha256_hex(const uint8_t* data, size_t len) {
  uint8_t digest[SHA256_DIGEST_LENGTH];
  SHA256(data, len, digest);
  return to_hex(digest, sizeof(digest));
}

std::vector<uint8_t> read_file(const std::string& path) {
  std::ifstream f(path, std::ios::binary);
  if (!f) {
    std::cerr << "cannot open: " << path << "\n";
    std::exit(2);
  }
  return {std::istreambuf_iterator<char>(f), {}};
}

bool has_flag(int argc, char** argv, const std::string& flag) {
  for (int i = 1; i < argc; ++i) {
    if (flag == argv[i]) return true;
  }
  return false;
}

std::string get_arg(int argc, char** argv, const std::string& flag,
                    const std::string& fallback = "") {
  for (int i = 1; i + 1 < argc; ++i) {
    if (flag == argv[i]) return argv[i + 1];
  }
  return fallback;
}

size_t spec_index(int argc, char** argv) {
  size_t idx = static_cast<size_t>(std::atoi(get_arg(argc, argv, "--spec", "0").c_str()));
  if (idx >= kNumZkSpecs) {
    std::cerr << "--spec out of range (0.." << kNumZkSpecs - 1 << ")\n";
    std::exit(2);
  }
  return idx;
}

void print_spec(size_t i) {
  const ZkSpecStruct& s = kZkSpecs[i];
  std::printf("  [%2zu] %s  attrs=%zu  version=%zu  hash=%s\n", i, s.system,
              s.num_attributes, s.version, s.circuit_hash);
}

// Compares a circuit blob's computed id against the hash the spec expects.
// This is the check that tells us whether a locally generated circuit is
// byte-compatible with the blobs Longfellow ships.
bool check_blob(const std::vector<uint8_t>& blob, size_t idx) {
  const ZkSpecStruct& spec = kZkSpecs[idx];
  std::printf("blob:        %zu bytes\n", blob.size());
  std::printf("sha256:      %s\n", sha256_hex(blob.data(), blob.size()).c_str());

  uint8_t id[32];
  if (circuit_id(id, blob.data(), blob.size(), &spec) != 1) {
    std::printf("circuit_id:  FAILED to parse blob against spec %zu\n", idx);
    return false;
  }
  std::string got = to_hex(id, sizeof(id));
  bool ok = got == std::string(spec.circuit_hash);
  std::printf("circuit_id:  %s\n", got.c_str());
  std::printf("spec hash:   %s\n", spec.circuit_hash);
  std::printf("match:       %s\n", ok ? "OK" : "MISMATCH");
  return ok;
}

}  // namespace

int main(int argc, char** argv) {
  if (has_flag(argc, argv, "--list")) {
    std::printf("kZkSpecs (%d entries):\n", kNumZkSpecs);
    for (size_t i = 0; i < kNumZkSpecs; ++i) print_spec(i);
    return 0;
  }

  if (has_flag(argc, argv, "--generate")) {
    size_t idx = spec_index(argc, argv);
    std::string out_path = get_arg(argc, argv, "--out");
    if (out_path.empty()) {
      std::cerr << "--generate requires --out <path>\n";
      return 2;
    }
    std::printf("generating circuit for spec:\n");
    print_spec(idx);

    uint8_t* circuit = nullptr;
    size_t circuit_len = 0;
    auto start = std::chrono::steady_clock::now();
    auto rc = generate_circuit(&kZkSpecs[idx], &circuit, &circuit_len);
    auto elapsed = std::chrono::steady_clock::now() - start;
    if (rc != CIRCUIT_GENERATION_SUCCESS) {
      std::cerr << "circuit generation failed: " << rc << "\n";
      return 3;
    }
    std::printf("generated in %.2f s\n",
                std::chrono::duration<double>(elapsed).count());

    std::vector<uint8_t> blob(circuit, circuit + circuit_len);
    std::free(circuit);

    std::ofstream f(out_path, std::ios::binary);
    f.write(reinterpret_cast<const char*>(blob.data()), blob.size());
    f.close();
    std::printf("wrote %s\n", out_path.c_str());

    return check_blob(blob, idx) ? 0 : 4;
  }

  std::string check_path = get_arg(argc, argv, "--check");
  if (!check_path.empty()) {
    size_t idx = spec_index(argc, argv);
    std::printf("checking %s against spec:\n", check_path.c_str());
    print_spec(idx);
    return check_blob(read_file(check_path), idx) ? 0 : 4;
  }

  std::cerr
      << "usage:\n"
      << "  circuit_tool --list\n"
      << "  circuit_tool --generate [--spec N] --out <path>\n"
      << "  circuit_tool --check <path> [--spec N]\n";
  return 2;
}
