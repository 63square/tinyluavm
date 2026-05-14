#!/usr/bin/env python3
"""Run the full internal test suite through the micro-VM.

For each .luau file in tests/internal/, this:
  1. Compiles it via the offline compiler.
  2. Predecodes the macro-VM bytecode + this user bytecode together into a
     single `{m={K,F}, u={K,F}}` Luau module (the combined `inputData`).
  3. Generates a runner Luau script that requires the micro-VM and the
     inputData module, builds the shadow env exposing the op helpers,
     and calls the micro-VM with the new 4-argument signature.
  4. Spawns `luau` on the runner script and captures output.
  5. Greps the output for "<N> passed, <M> failed" to determine pass/fail.

Exit code: 0 if every test passes, 1 otherwise.
"""
from __future__ import annotations
import sys, pathlib, subprocess, re, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
COMPILER = ROOT / "tools" / "compiler.py"
PREDEC = ROOT / "tools" / "predecode.py"
BUILD = ROOT / "build"
TESTS = ROOT / "tests" / "internal"


def ensure_macro_bin() -> pathlib.Path:
    bin_path = BUILD / "macrovm.bin"
    if not bin_path.exists():
        subprocess.check_call([sys.executable, str(ROOT / "tools" / "build.py")])
    return bin_path


# Shared bottom-half of every runner. The micro-VM resolves macro-VM
# globals (string.byte, table.pack, etc.) through the caller's env,
# which here is just `getfenv()` of the runner script.
_RUNNER_TEMPLATE = """--!nocheck
local micro = require("./_tinyvm")
local D     = require("./_input")

micro(D, getfenv())
"""


def run_one(luau_src: pathlib.Path) -> tuple[bool, str]:
    macro_bin = ensure_macro_bin()
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        user_bin = td / "user.bin"
        r = subprocess.run(
            [sys.executable, str(COMPILER), str(luau_src), str(user_bin)],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            return False, f"compile failed: {r.stderr.strip()[:200]}"

        input_mod = BUILD / "_input.luau"
        r = subprocess.run(
            [sys.executable, str(PREDEC), str(macro_bin), str(input_mod),
             "--for-micro", "--user", str(user_bin)],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            return False, f"predecode failed: {r.stderr.strip()[:200]}"

        # Stage the micro-VM next to the input module so the runner's
        # relative requires resolve.
        tinyvm_copy = BUILD / "_tinyvm.luau"
        tinyvm_copy.write_text(
            (SRC / "tinyvm.luau").read_text(encoding="latin-1"),
            encoding="latin-1", newline="",
        )

        runner = BUILD / "_runner_test.luau"
        runner.write_text(_RUNNER_TEMPLATE, encoding="utf-8")
        r2 = subprocess.run(
            ["luau", str(runner)],
            capture_output=True, text=True, timeout=180,
        )
        runner.unlink()
        input_mod.unlink()
        tinyvm_copy.unlink()

        out = (r2.stdout or "") + (r2.stderr or "")
        m = re.search(r"(\d+)\s+passed,\s+(\d+)\s+failed", out)
        if m:
            npass, nfail = int(m.group(1)), int(m.group(2))
            return (nfail == 0), f"{npass}/{npass+nfail} passed"
        if r2.returncode == 0:
            return False, f"no test-summary output (silent pass?): stdout='{out.strip()[:80]}'"
        return False, f"failed (rc={r2.returncode}): {out.strip().splitlines()[-1] if out else ''}"


def main():
    files = sorted(TESTS.glob("*.luau"))
    if not files:
        print("no tests in tests/internal/")
        sys.exit(0)
    overall_ok = True
    for f in files:
        ok, msg = run_one(f)
        flag = "PASS" if ok else "FAIL"
        print(f"  {flag}  {f.name}  ({msg})")
        if not ok:
            overall_ok = False
    print()
    print("OK" if overall_ok else "FAILED")
    sys.exit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
