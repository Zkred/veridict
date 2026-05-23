"""Build minimal ISO 18013-5 MDOC credentials for the anonymous reviewer system.

This module constructs MDOC documents that Longfellow's `run_mdoc_prover` can
consume. We use a custom docType (`org.example.reviewer.v1`) and a custom
namespace (`org.example.reviewer`) with two attributes: `role` and `org`.

The structure follows ISO 18013-5 section 8 (CBOR encoding), specifically:
- IssuerSignedItem entries are bstr-wrapped (CBOR tag 24)
- MSO is signed with COSE_Sign1 using ECDSA P-256 (ES256)
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
from dataclasses import dataclass

import cbor2
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
)

DOC_TYPE = "org.example.reviewer.v1"
# Longfellow's parser only finds attributes whose namespace appears in the
# hardcoded `kSupportedNamespaces` array in
# `lib/circuits/mdoc/mdoc_attribute_ids.h`. To use this custom namespace you
# MUST apply patches/add-reviewer-namespace.patch to your Longfellow checkout
# and rebuild. See docs/mdoc-format-notes.md.
NAMESPACE = "org.example.reviewer"

# COSE_Sign1 header label for the algorithm
COSE_ALG_LABEL = 1
COSE_ES256 = -7


@dataclass
class Attribute:
    name: str
    value: object  # passed through cbor2.dumps as-is


def _issuer_signed_item(digest_id: int, attr: Attribute) -> bytes:
    """Returns the CBOR-encoded, bstr-wrapped IssuerSignedItem."""
    item = {
        "digestID": digest_id,
        "random": os.urandom(16),
        "elementIdentifier": attr.name,
        "elementValue": attr.value,
    }
    # bstr-wrap: outer wrapper is `bytes(cbor)` then tagged with 24
    inner = cbor2.dumps(item)
    return cbor2.dumps(cbor2.CBORTag(24, inner))


def _coordinate_bytes(point: int) -> bytes:
    return point.to_bytes(32, "big")


def _cose_sign1(payload: bytes, signing_key: ec.EllipticCurvePrivateKey) -> list:
    """Returns a COSE_Sign1 message [phdr, uhdr, payload, signature]."""
    protected = cbor2.dumps({COSE_ALG_LABEL: COSE_ES256})
    unprotected: dict = {}
    sig_structure = ["Signature1", protected, b"", payload]
    to_be_signed = cbor2.dumps(sig_structure)

    der_sig = signing_key.sign(to_be_signed, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der_sig)
    raw_sig = _coordinate_bytes(r) + _coordinate_bytes(s)
    return [protected, unprotected, payload, raw_sig]


def build_session_transcript(pr_key: str) -> bytes:
    """ISO 18013-5 SessionTranscript = [DEBytes, ERBytes, Handover].

    We don't have an NFC handover so DEBytes and ERBytes are null. The
    Handover binds the credential to a specific review event.
    """
    handover = ["AnonReviewv1", hashlib.sha256(pr_key.encode()).digest()]
    return cbor2.dumps([None, None, handover])


def _device_signature(
    transcript: bytes,
    doc_type: str,
    device_namespaces: bytes,
    device_key: ec.EllipticCurvePrivateKey,
) -> list:
    """Builds DeviceAuth.deviceSignature (COSE_Sign1) per ISO 18013-5 §9.1.3.4."""
    # DeviceAuthentication = ["DeviceAuthentication", SessionTranscript, DocType, DeviceNameSpacesBytes]
    device_auth = [
        "DeviceAuthentication",
        cbor2.loads(transcript),
        doc_type,
        cbor2.CBORTag(24, device_namespaces),
    ]
    payload = cbor2.dumps(cbor2.CBORTag(24, cbor2.dumps(device_auth)))
    return _cose_sign1(payload, device_key)


def build_mdoc(
    attributes: list[Attribute],
    issuer_key: ec.EllipticCurvePrivateKey,
    device_key: ec.EllipticCurvePrivateKey,
    pr_key: str,
    validity_days: int = 30,
) -> tuple[bytes, bytes]:
    """Returns (mdoc_bytes, session_transcript_bytes).

    The transcript must be passed to `run_mdoc_prover` as the --transcript
    argument; it's the binding between the credential and the review event.
    """
    """Builds and signs a minimal MDOC. Returns the CBOR-encoded bytes."""
    # 1. Build IssuerSignedItems and their digests for the MSO
    signed_items: list[bytes] = []
    digests: dict[int, bytes] = {}
    for i, attr in enumerate(attributes):
        item_cbor = _issuer_signed_item(i, attr)
        signed_items.append(item_cbor)
        digests[i] = hashlib.sha256(item_cbor).digest()

    # 2. Build the MSO
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    valid_until = now + dt.timedelta(days=validity_days)
    device_numbers = device_key.public_key().public_numbers()
    mso = {
        "version": "1.0",
        "digestAlgorithm": "SHA-256",
        "valueDigests": {NAMESPACE: digests},
        # Standard COSE_Key for EC2 P-256 (RFC 8152). The Longfellow parser's
        # `dev_key_pkx_` / `dev_key_pky_` variables are misnamed; they hold
        # CBOR byte positions of the crv (-1) and x (-2) entries, which the
        # ZK circuit then uses to extract the actual public key elsewhere.
        # Verified against the known-good test MDOC in mdoc_examples.h, which
        # uses exactly this layout (-1: crv, -2: x, -3: y).
        "deviceKeyInfo": {
            "deviceKey": {
                1: 2,    # kty: EC2
                -1: 1,   # crv: P-256
                -2: _coordinate_bytes(device_numbers.x),
                -3: _coordinate_bytes(device_numbers.y),
            },
        },
        "docType": DOC_TYPE,
        "validityInfo": {
            "signed": cbor2.CBORTag(0, now.strftime("%Y-%m-%dT%H:%M:%SZ")),
            "validFrom": cbor2.CBORTag(0, now.strftime("%Y-%m-%dT%H:%M:%SZ")),
            "validUntil": cbor2.CBORTag(
                0, valid_until.strftime("%Y-%m-%dT%H:%M:%SZ")
            ),
        },
    }
    mso_payload = cbor2.dumps(cbor2.CBORTag(24, cbor2.dumps(mso)))
    issuer_auth = _cose_sign1(mso_payload, issuer_key)

    # 3. Compute the device signature over the SessionTranscript for this PR.
    # The Longfellow ZK circuit verifies this against the deviceKey above
    # using the same transcript passed via --transcript to the prover.
    transcript = build_session_transcript(pr_key)
    device_namespaces = cbor2.dumps({})  # no device-side attributes
    device_signature = _device_signature(
        transcript, DOC_TYPE, device_namespaces, device_key
    )

    # 4. Assemble the document
    document = {
        "docType": DOC_TYPE,
        "issuerSigned": {
            "nameSpaces": {
                NAMESPACE: [cbor2.loads(item) for item in signed_items],
            },
            "issuerAuth": issuer_auth,
        },
        "deviceSigned": {
            "nameSpaces": cbor2.CBORTag(24, device_namespaces),
            "deviceAuth": {
                "deviceSignature": device_signature,
            },
        },
    }

    response = {
        "version": "1.0",
        "documents": [document],
        "status": 0,
    }
    return cbor2.dumps(response), transcript


def issuer_public_key_hex(key: ec.EllipticCurvePrivateKey) -> tuple[str, str]:
    """Returns (pkx, pky) as 0x-prefixed hex strings for Longfellow."""
    nums = key.public_key().public_numbers()
    return f"0x{nums.x:064x}", f"0x{nums.y:064x}"


def load_or_create_issuer_key(path: str) -> ec.EllipticCurvePrivateKey:
    """Loads a P-256 issuer key from PEM, or generates and persists one."""
    if os.path.exists(path):
        with open(path, "rb") as fh:
            return serialization.load_pem_private_key(fh.read(), password=None)
    key = ec.generate_private_key(ec.SECP256R1())
    with open(path, "wb") as fh:
        fh.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    return key
