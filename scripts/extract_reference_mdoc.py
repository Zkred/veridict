"""Extract a known-good test MDOC from Longfellow's mdoc_examples.h.

Longfellow ships hardcoded MDOC byte arrays inside `mdoc_tests[]`. This script
parses that C-style array literal out of the header and writes the raw bytes
to a file we can decode with `cbor2` and use as a structural reference.

Usage:
  python scripts/extract_reference_mdoc.py \
      --header /path/to/longfellow-zk/lib/circuits/mdoc/mdoc_examples.h \
      --index 0 \
      --out reference.mdoc
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

# Match  uint8_t mdoc[5000] = { 0xa3, 0x67, ... } -- the LAST {} block in the
# selected test struct is the `mdoc` field (the prior ones are `transcript`).


def extract_test_struct(text: str, index: int) -> str:
    """Returns the body of the i-th MdocTests literal."""
    start_marker = "mdoc_tests[] = {"
    p = text.find(start_marker)
    if p < 0:
        sys.exit("mdoc_tests[] = { not found in header")
    p += len(start_marker)

    # Walk top-level brace groups, each one is a MdocTests struct.
    depth = 0
    structs: list[tuple[int, int]] = []
    cur_start = -1
    for i in range(p, len(text)):
        ch = text[i]
        if ch == "{":
            if depth == 0:
                cur_start = i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and cur_start >= 0:
                structs.append((cur_start, i))
                cur_start = -1
                if len(structs) > index:
                    break
        elif depth == 0 and ch == "}" and text[i:i+2] == "};":
            break
    if index >= len(structs):
        sys.exit(f"only found {len(structs)} test structs (asked for {index})")
    s, e = structs[index]
    return text[s:e]


def last_byte_array(struct_body: str) -> bytes:
    """The last {0x..,...} array in the struct is the mdoc field."""
    arrays = re.findall(r"\{([^{}]+)\}", struct_body)
    if not arrays:
        sys.exit("no byte arrays found in struct body")
    # The transcript field has a fixed size of 1024 but its initializer can be
    # shorter; the mdoc field is always the LAST array literal in the struct.
    body = arrays[-1]
    bytes_out = bytearray()
    for tok in body.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok.startswith("0x") or tok.startswith("0X"):
            bytes_out.append(int(tok, 16))
        elif tok.isdigit():
            bytes_out.append(int(tok))
        else:
            sys.exit(f"unrecognized token in byte array: {tok!r}")
    return bytes(bytes_out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--header", required=True, type=pathlib.Path)
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    args = ap.parse_args()

    text = args.header.read_text()
    body = extract_test_struct(text, args.index)
    data = last_byte_array(body)
    args.out.write_bytes(data)
    print(f"wrote {len(data)} bytes to {args.out}")


if __name__ == "__main__":
    main()
