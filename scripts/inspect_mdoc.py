"""Decode an MDOC and print its structure in a format suitable for diffing.

Run against both the Longfellow reference MDOC and our generated one to see
exactly where the wire format diverges. Longfellow's parser
(`ParsedMdoc::parse_device_response`) walks these specific paths:

  documents[0].docType                              (text)
  documents[0].issuerSigned.issuerAuth              (COSE_Sign1 array, 4 elts)
  documents[0].issuerSigned.issuerAuth[2]           (tagged MSO bytes)
  documents[0].issuerSigned.issuerAuth[3]           (issuer signature)
  documents[0].issuerSigned.nameSpaces.<supported>  (array of tagged items)
  documents[0].deviceSigned.deviceAuth.deviceSignature[3]  (device sig)

Inside the MSO (after stripping tag 24):
  validityInfo, validFrom, validUntil
  deviceKeyInfo.deviceKey  (CBOR map; the parser does lookup_negative(-1) and
                            lookup_negative(-2) for pkx and pky — this is NOT
                            the standard COSE_Key layout, which uses -2/-3.
                            See mdoc_witness.h:255–263.)
  valueDigests.<namespace>.{digestID: bytes}

Each value must be exactly findable at those paths or the prover errors out.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

import cbor2


SUPPORTED_NAMESPACES = {
    "org.iso.18013.5.1",
    "org.iso.18013.5.1.aamva",
    "eu.europa.ec.av.1",
    "eu.europa.ec.eudi.pid.1",
    "org.iso.23220.1",
    "org.iso.23220.photoID.1",
    "org.iso.23220.dtc.1",
    "in.gov.uidai.aadhaar.1",
    "org.example.reviewer",  # added by patches/add-reviewer-namespace.patch
}


def _summarize(v: Any, depth: int = 0) -> Any:
    if isinstance(v, bytes):
        return f"<bytes len={len(v)} hex_prefix={v[:8].hex()}>"
    if isinstance(v, cbor2.CBORTag):
        return {"__tag__": v.tag, "value": _summarize(v.value, depth + 1)}
    if isinstance(v, dict):
        return {str(k): _summarize(val, depth + 1) for k, val in v.items()}
    if isinstance(v, list):
        return [_summarize(x, depth + 1) for x in v]
    return v


def check(label: str, ok: bool, detail: str = "") -> None:
    sym = "OK  " if ok else "FAIL"
    print(f"  [{sym}] {label}" + (f"  -- {detail}" if detail else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mdoc", type=pathlib.Path)
    ap.add_argument("--json", action="store_true", help="dump full structure")
    args = ap.parse_args()

    data = args.mdoc.read_bytes()
    print(f"== {args.mdoc} ({len(data)} bytes)")
    try:
        root = cbor2.loads(data)
    except Exception as e:
        print(f"  fatal: cannot decode CBOR: {e}")
        sys.exit(1)

    if args.json:
        print(json.dumps(_summarize(root), indent=2, default=str))

    check("root is dict", isinstance(root, dict))
    docs = root.get("documents") if isinstance(root, dict) else None
    check("has documents[]", isinstance(docs, list) and len(docs) > 0)
    if not docs:
        sys.exit(1)

    doc0 = docs[0]
    check("documents[0] is dict", isinstance(doc0, dict))
    doctype = doc0.get("docType")
    check("documents[0].docType is text", isinstance(doctype, str),
          f"docType={doctype!r}")

    issuer_signed = doc0.get("issuerSigned", {})
    check("issuerSigned present", bool(issuer_signed))

    ia = issuer_signed.get("issuerAuth")
    check("issuerAuth is 4-element list", isinstance(ia, list) and len(ia) == 4)
    if isinstance(ia, list) and len(ia) == 4:
        check("issuerAuth[0] is bytes (protected hdr)", isinstance(ia[0], bytes))
        check("issuerAuth[1] is dict (unprotected hdr)", isinstance(ia[1], dict))
        check("issuerAuth[2] is bytes (tagged MSO)", isinstance(ia[2], bytes))
        check("issuerAuth[3] is bytes (signature)", isinstance(ia[3], bytes),
              f"len={len(ia[3]) if isinstance(ia[3], bytes) else 'n/a'} (expect 64 for raw ES256)")

    ns = issuer_signed.get("nameSpaces", {})
    check("nameSpaces present", isinstance(ns, dict))
    if isinstance(ns, dict):
        found_supported = [n for n in ns.keys() if n in SUPPORTED_NAMESPACES]
        check(
            "at least one supported namespace",
            bool(found_supported),
            f"present={list(ns.keys())}, supported_intersection={found_supported}",
        )
        for nsname, items in ns.items():
            if not isinstance(items, list):
                continue
            for i, item in enumerate(items):
                if not isinstance(item, cbor2.CBORTag) or item.tag != 24:
                    check(f"  {nsname}[{i}] is tag(24, bstr)", False)
                    continue
                inner = cbor2.loads(item.value)
                missing = [
                    f for f in ("digestID", "random", "elementIdentifier", "elementValue")
                    if f not in inner
                ]
                check(
                    f"  {nsname}[{i}] inner fields complete",
                    not missing,
                    f"missing={missing}, elementId={inner.get('elementIdentifier')!r}",
                )

    device_signed = doc0.get("deviceSigned", {})
    check("deviceSigned.deviceAuth.deviceSignature[3] present",
          isinstance(
              device_signed.get("deviceAuth", {}).get("deviceSignature"),
              list,
          )
          and len(device_signed["deviceAuth"]["deviceSignature"]) >= 4)

    # MSO inspection
    if isinstance(ia, list) and len(ia) == 4 and isinstance(ia[2], bytes):
        try:
            tagged = cbor2.loads(ia[2])
            mso_bytes = tagged.value if isinstance(tagged, cbor2.CBORTag) else ia[2]
            mso = cbor2.loads(mso_bytes)
        except Exception as e:
            check("MSO decodes", False, str(e))
            return
        check("MSO is dict", isinstance(mso, dict))
        for key in ("validityInfo", "valueDigests", "deviceKeyInfo"):
            check(f"MSO.{key} present", key in mso)
        dki = mso.get("deviceKeyInfo", {})
        dk = dki.get("deviceKey", {})
        if isinstance(dk, dict):
            print(f"  deviceKey labels present: {sorted(dk.keys(), key=lambda x: (isinstance(x,int), x))}")
            # The Longfellow parser does lookup_negative(-1) and lookup_negative(-2)
            # for pkx and pky. If those keys are missing the prover will fail with
            # MDOC_PROVER_DEVICE_KEY_MISSING.
            # Standard COSE_Key for EC2 P-256: -1=crv(=1), -2=x bytes, -3=y bytes
            check("deviceKey has crv at -1", -1 in dk)
            check("deviceKey has x at -2", -2 in dk and isinstance(dk[-2], bytes))
            check("deviceKey has y at -3", -3 in dk and isinstance(dk[-3], bytes))
            if -2 in dk and isinstance(dk[-2], bytes):
                check("deviceKey[-2] (x) is 32 bytes", len(dk[-2]) == 32,
                      f"got len={len(dk[-2])}")
            if -3 in dk and isinstance(dk[-3], bytes):
                check("deviceKey[-3] (y) is 32 bytes", len(dk[-3]) == 32,
                      f"got len={len(dk[-3])}")


if __name__ == "__main__":
    main()
