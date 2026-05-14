#!/usr/bin/env python3
"""Run the full internal test suite through the tinyvm bundle.

For each .luau file in tests/internal/, this:
  1. Compiles it via the offline compiler.
  2. Generates a runner Luau script that loads build/tinyvm-bundled.luau and
     executes the user bytecode against a writable _G shadow.
  3. Spawns `luau` on the runner script and captures output.
  4. Greps the output for "<N> passed, <M> failed" to determine pass/fail.

Exit code: 0 if every test passes, 1 otherwise.
"""
from __future__ import annotations
import sys, pathlib, subprocess, re, tempfile, os

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPILER = ROOT / "tools" / "compiler.py"
BUILD = ROOT / "build"
BUNDLE = BUILD / "tinyvm-bundled.luau"
TESTS = ROOT / "tests" / "internal"

def ensure_bundle():
    if not BUNDLE.exists():
        subprocess.check_call([sys.executable, str(ROOT/"tools"/"build.py")])

def _hex(data: bytes) -> str:
    return "".join(f"\\x{b:02x}" for b in data)

def run_one(luau_src: pathlib.Path) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        ubin = td / "user.bin"
        r = subprocess.run(
            [sys.executable, str(COMPILER), str(luau_src), str(ubin)],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            return False, f"compile failed: {r.stderr.strip()[:200]}"
        data = ubin.read_bytes()

        runner = BUILD / "_runner_test.luau"
        runner.write_text(
            "--!nocheck\n"
            "local play = require(\"./tinyvm-bundled\")\n"
            f'local user = "{_hex(data)}"\n'
            "local env = setmetatable({}, {__index=_G})\n"
            "env._G = env\n"
            f"play(user, env, {luau_src.name!r})\n",
            encoding="utf-8",
        )
        r2 = subprocess.run(
            ["luau", str(runner)],
            capture_output=True, text=True, timeout=180,
        )
        runner.unlink()
        out = (r2.stdout or "") + (r2.stderr or "")
        m = re.search(r"(\d+)\s+passed,\s+(\d+)\s+failed", out)
        if m:
            npass, nfail = int(m.group(1)), int(m.group(2))
            return (nfail == 0), f"{npass}/{npass+nfail} passed"
        if r2.returncode == 0:
            return False, f"no test-summary output (silent pass?): stdout='{out.strip()[:80]}'"
        return False, f"failed (rc={r2.returncode}): {out.strip().splitlines()[-1] if out else ''}"

def main():
    ensure_bundle()
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
