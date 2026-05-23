# Longfellow MDOC compatibility — wire format gotchas

These are the parser invariants you must satisfy for `run_mdoc_prover` to
accept a freshly-minted MDOC. They are extracted from
`lib/circuits/mdoc/mdoc_witness.h` (the `ParsedMdoc::parse_device_response`
function) and `lib/circuits/mdoc/mdoc_attribute_ids.h`.

If `MDOC_PROVER_*_MISSING` errors show up at runtime, work down this list.

## 1. Namespace must be in the hardcoded supported list

Longfellow loops over the array `kSupportedNamespaces`:

```cpp
for (const char* sn : kSupportedNamespaces) {
  auto mldns = ns[1].lookup(resp, strlen(sn), (const uint8_t*)sn, di);
  if (mldns == nullptr) continue;
  // ... parse attributes here
}
```

If your namespace isn't in that list, the loop silently skips it and
`attributes_` stays empty. The prover then fails downstream with a
hash-mismatch error. **The fix is to patch the Longfellow source** —
see `patches/add-reviewer-namespace.patch`.

## 2. Device key uses STANDARD COSE_Key layout (variable names mislead)

The parser (mdoc_witness.h:255–263) does:

```cpp
auto npkx = ndk[1].lookup_negative(-1, dev_key_pkx_.ndx);
auto npky = ndk[1].lookup_negative(-2, dev_key_pky_.ndx);
```

The variable names `dev_key_pkx_` and `dev_key_pky_` are misleading. They
hold CBOR byte *positions* of the entries at keys -1 and -2, which the ZK
circuit later uses to extract the public key. Verified against the
known-good test MDOC: the reference uses **standard COSE_Key for EC2 P-256**:

```
deviceKey = {
    1: 2,             // kty: EC2
    -1: 1,            // crv: P-256
    -2: <32 bytes>,   // x coordinate
    -3: <32 bytes>,   // y coordinate
}
```

Earlier draft of this doc was wrong about labels — corrected after running
`scripts/inspect_mdoc.py` against the reference MDOC.

## 3. Each IssuerSignedItem must be tag(24, bstr(map))

The parser dereferences `tattr->children_[0].u_.string.{pos,len}` — that's
the inner bytestring of a `CBORTag(24, bytes(cbor_map))`. The inner map
needs all four fields:

- `digestID` (uint)
- `random` (bstr, typically 16 bytes)
- `elementIdentifier` (tstr)
- `elementValue` (any)

Missing any field → `MDOC_PROVER_ATTRIBUTE_{EI,EV,DID,RANDOM}_MISSING`.

## 4. issuerAuth is a 4-element COSE_Sign1 array

```
issuerAuth = [
    protected_header_bstr,   # CBOR-encoded map containing {1: -7} for ES256
    unprotected_header_map,  # usually empty {}
    payload_bstr,            # CBORTag(24, bstr(MSO)) — payload is itself tagged
    signature_bstr,          # 64-byte raw r||s, NOT DER
]
```

The signature in COSE_Sign1 is the *raw* concatenation of r and s, each
zero-padded to 32 bytes. If you sign with OpenSSL/Python `cryptography`
defaults, you get DER — decode with `decode_dss_signature` and concat.

## 5. MSO field names and positions

The parser hardcodes the byte lengths of MSO key names (see
`mdoc_constants.h`). Names must match exactly:

- `validityInfo` (12 bytes)
- `validFrom` (9), `validUntil` (10)
- `deviceKeyInfo` (13), `deviceKey` (9)
- `valueDigests` (12)

CBOR map ordering doesn't matter (the parser uses `lookup`), but the
field names must be exact.

## 6. deviceSigned must have a deviceSignature array of length ≥ 4

```cpp
auto dsi = da[1].lookup(resp, 15, (uint8_t*)"deviceSignature", di);
auto ndksig = dsi[1].index(3);
```

The parser needs `deviceAuth.deviceSignature[3]` to exist. It does **not**
verify the device signature in the parser — that happens later in the ZK
circuit, where the device key from the MSO is used to verify a signature
over the session transcript.

For the hackathon, we ship a stub (`[b"", {}, None, b""]`) which parses
fine. To get an end-to-end valid proof you also need a real device
signature; see `docs/device-signature.md` (TODO) for the structure.

## 7. The transcript is part of the ZK proof, not the MDOC

`run_mdoc_prover` takes the session `transcript` as a separate parameter.
We derive it from the PR key (`sha256(owner/repo/pr#@sha)`) to bind each
review proof to a specific commit.

## Validation workflow

```bash
# 1. Get a known-good MDOC and inspect it
python scripts/extract_reference_mdoc.py \
    --header ../longfellow-zk/lib/circuits/mdoc/mdoc_examples.h \
    --index 0 --out reference.mdoc
python scripts/inspect_mdoc.py reference.mdoc

# 2. Generate one with our builder
python -c "
from issuer.mdoc_builder import Attribute, build_mdoc, load_or_create_issuer_key
from cryptography.hazmat.primitives.asymmetric import ec
key = load_or_create_issuer_key('issuer_key.pem')
device = ec.generate_private_key(ec.SECP256R1()).public_key()
bytes_ = build_mdoc([Attribute('role', 'maintainer'), Attribute('org', 'myorg')],
                    key, device)
open('ours.mdoc', 'wb').write(bytes_)
"
python scripts/inspect_mdoc.py ours.mdoc

# 3. Diff. Every check must say [OK ] before the prover will accept.
diff <(python scripts/inspect_mdoc.py reference.mdoc) \
     <(python scripts/inspect_mdoc.py ours.mdoc)
```
