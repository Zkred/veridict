// Differential test: portable_crypto.h vs OpenSSL, on the exact operations
// Longfellow performs. Any divergence here would silently corrupt proofs.

#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <sys/random.h>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <vector>

// Real OpenSSL, at global scope.
#include "openssl/sha.h"
#include "openssl/evp.h"
#include "openssl/rand.h"

// Our shim, isolated in a namespace. Its own system includes are already
// satisfied above, so the include guards make them no-ops.
namespace port {
#include "util/portable_crypto.h"
}

static int failures = 0;

static void expect_eq(const uint8_t* a, const uint8_t* b, size_t n,
                      const char* what, size_t detail) {
  if (memcmp(a, b, n) != 0) {
    std::printf("FAIL  %s (len=%zu)\n", what, detail);
    ++failures;
  }
}

int main() {
  // --- SHA-256 one-shot, across every length class that exercises padding,
  // block boundaries, and the 55/56/57-byte length-field edge cases.
  size_t lens[] = {0,   1,   2,   3,   55,  56,  57,  63,  64,   65,
                   119, 120, 127, 128, 129, 191, 192, 255, 1000, 100000};
  for (size_t li = 0; li < sizeof(lens) / sizeof(lens[0]); ++li) {
    size_t n = lens[li];
    std::vector<uint8_t> msg(n ? n : 1);
    if (n) RAND_bytes(msg.data(), n);

    uint8_t want[32], got[32];
    ::SHA256(msg.data(), n, want);
    port::SHA256(msg.data(), n, got);
    expect_eq(want, got, 32, "sha256 one-shot", n);
  }

  // --- SHA-256 streamed in awkward chunks, which is how Longfellow's
  // Transcript feeds it.
  {
    std::vector<uint8_t> msg(5000);
    RAND_bytes(msg.data(), msg.size());
    size_t chunks[] = {1, 7, 31, 32, 63, 64, 65, 127, 1000};

    for (size_t ci = 0; ci < sizeof(chunks) / sizeof(chunks[0]); ++ci) {
      size_t step = chunks[ci];
      SHA256_CTX oc;
      port::SHA256_CTX pc;
      SHA256_Init(&oc);
      port::SHA256_Init(&pc);
      for (size_t off = 0; off < msg.size(); off += step) {
        size_t take = std::min(step, msg.size() - off);
        SHA256_Update(&oc, msg.data() + off, take);
        port::SHA256_Update(&pc, msg.data() + off, take);
      }
      uint8_t want[32], got[32];
      SHA256_Final(want, &oc);
      port::SHA256_Final(got, &pc);
      expect_eq(want, got, 32, "sha256 streamed", step);
    }
  }

  // --- CopyState semantics: snapshot a running hash, extend both, compare.
  // This is what SHA256::CopyState relies on via plain struct assignment.
  {
    std::vector<uint8_t> a(100), b(200);
    RAND_bytes(a.data(), a.size());
    RAND_bytes(b.data(), b.size());

    SHA256_CTX oc;
    port::SHA256_CTX pc;
    SHA256_Init(&oc);
    port::SHA256_Init(&pc);
    SHA256_Update(&oc, a.data(), a.size());
    port::SHA256_Update(&pc, a.data(), a.size());

    SHA256_CTX oc2 = oc;
    port::SHA256_CTX pc2 = pc;
    SHA256_Update(&oc2, b.data(), b.size());
    port::SHA256_Update(&pc2, b.data(), b.size());

    uint8_t want[32], got[32];
    SHA256_Final(want, &oc2);
    port::SHA256_Final(got, &pc2);
    expect_eq(want, got, 32, "sha256 copied-state", 0);
  }

  // --- AES-256-ECB, exactly as PRF::Eval calls it: one 16-byte block.
  for (int trial = 0; trial < 200; ++trial) {
    uint8_t key[32], in[16];
    RAND_bytes(key, sizeof(key));
    RAND_bytes(in, sizeof(in));

    uint8_t want[32] = {0};
    int want_len = 16;
    EVP_CIPHER_CTX* oc = EVP_CIPHER_CTX_new();
    if (EVP_EncryptInit_ex(oc, EVP_aes_256_ecb(), nullptr, key, nullptr) != 1) {
      std::printf("FAIL  openssl init\n");
      return 1;
    }
    if (EVP_EncryptUpdate(oc, want, &want_len, in, 16) != 1) {
      std::printf("FAIL  openssl update\n");
      return 1;
    }
    EVP_CIPHER_CTX_free(oc);

    uint8_t got[32] = {0};
    int got_len = 16;
    port::EVP_CIPHER_CTX* pc = port::EVP_CIPHER_CTX_new();
    if (port::EVP_EncryptInit_ex(pc, port::EVP_aes_256_ecb(), nullptr, key,
                                 nullptr) != 1) {
      std::printf("FAIL  shim init\n");
      return 1;
    }
    if (port::EVP_EncryptUpdate(pc, got, &got_len, in, 16) != 1) {
      std::printf("FAIL  shim update\n");
      return 1;
    }
    port::EVP_CIPHER_CTX_free(pc);

    if (want_len != got_len) {
      std::printf("FAIL  aes out_len %d vs %d\n", want_len, got_len);
      ++failures;
    }
    expect_eq(want, got, 16, "aes-256-ecb block", trial);
  }

  // --- FIPS-197 C.3 known-answer test for AES-256, so a matching-but-wrong
  // pair of implementations cannot pass silently.
  {
    uint8_t key[32], in[16], want[16];
    for (int i = 0; i < 32; ++i) key[i] = static_cast<uint8_t>(i);
    for (int i = 0; i < 16; ++i) in[i] = static_cast<uint8_t>(i * 0x11);
    const uint8_t expected[16] = {0x8e, 0xa2, 0xb7, 0xca, 0x51, 0x67, 0x45, 0xbf,
                                  0xea, 0xfc, 0x49, 0x90, 0x4b, 0x49, 0x60, 0x89};
    memcpy(want, expected, 16);

    uint8_t got[32] = {0};
    int got_len = 16;
    port::EVP_CIPHER_CTX* pc = port::EVP_CIPHER_CTX_new();
    port::EVP_EncryptInit_ex(pc, port::EVP_aes_256_ecb(), nullptr, key, nullptr);
    port::EVP_EncryptUpdate(pc, got, &got_len, in, 16);
    port::EVP_CIPHER_CTX_free(pc);
    expect_eq(want, got, 16, "aes-256 FIPS-197 C.3 vector", 0);
  }

  // --- SHA-256 known-answer test ("abc").
  {
    const uint8_t expected[32] = {
        0xba, 0x78, 0x16, 0xbf, 0x8f, 0x01, 0xcf, 0xea, 0x41, 0x41, 0x40,
        0xde, 0x5d, 0xae, 0x22, 0x23, 0xb0, 0x03, 0x61, 0xa3, 0x96, 0x17,
        0x7a, 0x9c, 0xb4, 0x10, 0xff, 0x61, 0xf2, 0x00, 0x15, 0xad};
    uint8_t got[32];
    port::SHA256(reinterpret_cast<const uint8_t*>("abc"), 3, got);
    expect_eq(expected, got, 32, "sha256 NIST vector \"abc\"", 0);
  }

  // --- RAND_bytes: sanity only. Must fill and must not return constant.
  {
    uint8_t a[300] = {0}, b[300] = {0};
    if (port::RAND_bytes(a, sizeof(a)) != 1 ||
        port::RAND_bytes(b, sizeof(b)) != 1) {
      std::printf("FAIL  shim RAND_bytes returned failure\n");
      ++failures;
    } else if (memcmp(a, b, sizeof(a)) == 0) {
      std::printf("FAIL  shim RAND_bytes produced identical buffers\n");
      ++failures;
    }
  }

  std::printf(failures == 0 ? "\nALL PASS\n" : "\n%d FAILURES\n", failures);
  return failures == 0 ? 0 : 1;
}
