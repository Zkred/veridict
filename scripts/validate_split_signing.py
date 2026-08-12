#!/usr/bin/env python3
"""Validates that an MDOC signed in two places still proves and verifies.

The browser-side proving cutover splits MDOC construction across a trust
boundary: the issuer signs the MSO (having only the device *public* key), and the
holder separately signs the DeviceAuthentication bytes. If either half is
byte-wrong, Longfellow's parser rejects the document or the proof fails to
verify, so this exercises the whole path against the real prover and verifier.

    python3 scripts/validate_split_signing.py

Exits 0 only if a spliced MDOC produces a proof the verifier accepts.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "issuer"))

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from mdoc_builder import (  # noqa: E402
    Attribute,
    build_mdoc,
    issuer_public_key_hex,
    load_or_create_issuer_key,
    splice_device_signature,
)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CIRCUIT = os.path.join(
    ROOT, "prover/circuits",
    "8d079211715200ff06c5109639245502bfe94aa869908d31176aae4016182121",
)
PROVER = os.path.join(ROOT, "prover/build/prover_cli")
VERIFIER = os.path.join(ROOT, "prover/build/verifier_cli")
CLAIM = "org.example.reviewer:role:6a6d61696e7461696e6572"
DOC_TYPE = "org.example.reviewer.v1"


def main() -> int:
    for path in (CIRCUIT, PROVER, VERIFIER):
        if not os.path.exists(path):
            print(f"FAIL  missing {path}; run scripts/bootstrap.sh")
            return 1

    issuer_key = load_or_create_issuer_key(
        os.path.join(tempfile.gettempdir(), "veridict-split-test-issuer.pem")
    )

    # Stands in for the browser's non-extractable WebCrypto key. The point is
    # that build_mdoc never receives this object, only its public coordinates.
    device_key = ec.generate_private_key(ec.SECP256R1())
    pub = device_key.public_key().public_numbers()

    pr_key = "veridict/split-test/1/deadbeef"
    unsigned = build_mdoc(
        [Attribute("role", "maintainer"), Attribute("org", "veridict")],
        issuer_key,
        device_pub_x=pub.x,
        device_pub_y=pub.y,
        pr_key=pr_key,
    )
    print(f"unsigned mdoc    : {len(unsigned.mdoc)} bytes")
    print(f"device_tbs       : {len(unsigned.device_tbs)} bytes")
    print(f"sig_offset       : {unsigned.sig_offset}")

    # The placeholder must really be zeroes at the offset we advertise.
    slot = unsigned.mdoc[unsigned.sig_offset:unsigned.sig_offset + 64]
    if slot != b"\x00" * 64:
        print("FAIL  sig_offset does not point at the 64-byte placeholder")
        return 1

    # Holder signs. WebCrypto's ECDSA sign returns raw r||s, so convert the DER
    # that `cryptography` produces into the same form the browser will send.
    der = device_key.sign(unsigned.device_tbs, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    raw_sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    mdoc = splice_device_signature(unsigned, raw_sig)

    if len(mdoc) != len(unsigned.mdoc):
        print("FAIL  splicing changed the document length")
        return 1
    print(f"spliced mdoc     : {len(mdoc)} bytes")

    pkx, pky = issuer_public_key_hex(issuer_key)
    now = (datetime.now(timezone.utc) + timedelta(seconds=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    with tempfile.TemporaryDirectory() as tmp:
        mdoc_path = os.path.join(tmp, "split.mdoc")
        proof_path = os.path.join(tmp, "split.proof")
        with open(mdoc_path, "wb") as fh:
            fh.write(mdoc)

        prove = subprocess.run(
            [PROVER, "--mdoc", mdoc_path, "--pkx", pkx, "--pky", pky,
             "--transcript", unsigned.transcript.hex(), "--claim", CLAIM,
             "--now", now, "--out", proof_path, "--circuit", CIRCUIT],
            capture_output=True, timeout=300,
        )
        if prove.returncode != 0:
            print(f"FAIL  prover rejected the spliced MDOC: "
                  f"{prove.stderr.decode()[:400]}")
            return 1
        print(f"proof            : {os.path.getsize(proof_path)} bytes")

        verify = subprocess.run(
            [VERIFIER, "--proof", proof_path, "--pkx", pkx, "--pky", pky,
             "--transcript", unsigned.transcript.hex(), "--claim", CLAIM,
             "--now", now, "--doctype", DOC_TYPE, "--circuit", CIRCUIT],
            capture_output=True, timeout=300,
        )
        if verify.returncode != 0:
            print(f"FAIL  verifier rejected the proof: "
                  f"{verify.stderr.decode()[:400]}")
            return 1

    print("\nPASS  split-signed MDOC proves and verifies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
