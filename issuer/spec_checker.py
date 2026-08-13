"""Formal spec conformance check: mypy + pytest + Z3 + crosshair on PR files.

Kept for local development and the ci-preferred fallback. In production the gate
is sourced from the reviewed repository's CI instead (see issuer/spec_gate.py):
running these tools here executes attacker-influenced PR code in the process
that holds the signing key.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

# A PEP 316 contract line, e.g. "    pre: n >= 0" inside a docstring. Used to
# skip crosshair entirely on files that declare no contracts.
_CONTRACT_RE = re.compile(r"^\s*(pre|post)(_always)?:", re.M)


async def fetch_pr_files(
    owner: str, repo: str, sha: str,
    files: list[dict], token: str,
) -> dict[str, str]:
    """Fetch full content of each Python file at the PR head commit.

    Uses raw.githubusercontent.com so we get the post-PR file state, not the
    patch. Removed files are skipped.
    """
    contents: dict[str, str] = {}
    headers: dict[str, str] = {}
    if token and token != "DEV_NO_TOKEN":
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=15) as client:
        for f in files:
            name = f.get("filename", "")
            if not name.endswith(".py") or f.get("status") == "removed":
                continue
            r = await client.get(
                f"https://raw.githubusercontent.com/{owner}/{repo}/{sha}/{name}",
                headers=headers,
            )
            if r.status_code == 200:
                contents[name] = r.text
    return contents


def run_spec_check(file_contents: dict[str, str]) -> dict:
    """Run mypy + pytest on the given Python files in a temp directory.

    Returns:
      {"passed": bool, "skipped": bool, "mypy_ok": bool, "pytest_ok": bool,
       "has_tests": bool, "mypy_output": str, "pytest_output": str,
       "files_checked": int}
    """
    if not file_contents:
        return {
            "passed": True, "skipped": True,
            "reason": "no Python files in this PR",
        }

    with tempfile.TemporaryDirectory() as tmpdir:
        for fname, content in file_contents.items():
            fpath = Path(tmpdir) / fname
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(content, encoding="utf-8")

        # Run mypy only on implementation files. Test files are checked by
        # pytest; z3 files use wildcard imports that mypy can't resolve.
        impl_files = [
            f for f in file_contents
            if not (Path(f).name.startswith("test_") or Path(f).name.endswith("_test.py")
                    or Path(f).name.startswith("z3_") or Path(f).name.endswith("_z3.py"))
        ]
        if impl_files:
            mypy = subprocess.run(
                [sys.executable, "-m", "mypy", "--ignore-missing-imports",
                 "--no-error-summary", "--no-color-output"] +
                [str(Path(tmpdir) / f) for f in impl_files],
                capture_output=True, text=True, timeout=30,
            )
            mypy_ok = mypy.returncode == 0
            mypy_out = (mypy.stdout + mypy.stderr).strip()
        else:
            mypy_ok = True
            mypy_out = ""

        test_files = [
            f for f in file_contents
            if Path(f).name.startswith("test_") or Path(f).name.endswith("_test.py")
        ]
        pytest_ok = True
        pytest_out = ""
        if test_files:
            pt = subprocess.run(
                [sys.executable, "-m", "pytest", "--tb=short", "-q",
                 "--no-header", tmpdir],
                capture_output=True, text=True, timeout=60,
            )
            pytest_ok = pt.returncode == 0
            pytest_out = (pt.stdout + pt.stderr).strip()

        # Z3 formal property verification — run any z3_*.py file.
        z3_files = [
            f for f in file_contents
            if Path(f).name.startswith("z3_") or Path(f).name.endswith("_z3.py")
        ]
        z3_ok = True
        z3_out = ""
        has_z3 = bool(z3_files)
        if z3_files:
            for z3f in z3_files:
                z3r = subprocess.run(
                    [sys.executable, str(Path(tmpdir) / z3f)],
                    capture_output=True, text=True, timeout=60,
                )
                z3_ok = z3_ok and (z3r.returncode == 0)
                z3_out += (z3r.stdout + z3r.stderr).strip()

        # crosshair: does the implementation satisfy the contracts the spec
        # demands? mypy, pytest and Z3 between them establish that the code
        # typechecks, that the model's own tests pass, and that the spec is
        # self-consistent — none of them relate implementation to spec, and the
        # tests share the blind spots of the model that wrote the code.
        # Functions without pre/post contracts are skipped, so this is inert on
        # code that declares none.
        contract_files = [
            f for f in impl_files if _CONTRACT_RE.search(file_contents[f])
        ]
        crosshair_ok = True
        crosshair_out = ""
        has_contracts = bool(contract_files)
        if contract_files:
            ch = subprocess.run(
                [sys.executable, "-m", "crosshair", "check",
                 "--per_condition_timeout=20", *contract_files],
                cwd=tmpdir, capture_output=True, text=True, timeout=240,
            )
            crosshair_ok = ch.returncode == 0
            crosshair_out = (ch.stdout + ch.stderr).strip()

    return {
        "passed": mypy_ok and pytest_ok and z3_ok and crosshair_ok,
        "skipped": False,
        "mypy_ok": mypy_ok,
        "pytest_ok": pytest_ok,
        "z3_ok": z3_ok,
        "crosshair_ok": crosshair_ok,
        "has_tests": bool(test_files),
        "has_z3": has_z3,
        "has_contracts": has_contracts,
        "mypy_output": mypy_out[-600:],
        "pytest_output": pytest_out[-600:],
        "z3_output": z3_out[-600:],
        "crosshair_output": crosshair_out[-600:],
        "files_checked": len(file_contents),
    }
