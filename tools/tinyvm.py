#!/usr/bin/env python3
"""tinyvm CLI: compile a Luau source file and run it via the micro-VM.

Usage:
    python tools/tinyvm.py run <source.luau>
    python tools/tinyvm.py compile <source.luau> <output.bin>

The `run` subcommand:
    1. Compiles <source.luau> via tools/compiler.py.
    2. Predecodes the macro-VM + user bytecode into a combined Luau
       module of shape `{m={K,F}, u={K,F}}`.
    3. Generates a runner Luau script that requires the micro-VM and
       the input module, wires up the shadow env exposing the
       op-helper functions, and calls the micro-VM.
    4. Executes the runner with `luau` (must be on PATH).

The `compile` subcommand just produces the compiled bytecode file.
"""
from __future__ import annotations
import sys, pathlib, subprocess, argparse, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
COMPILER = ROOT / "tools" / "compiler.py"
PREDEC = ROOT / "tools" / "predecode.py"
BUILD = ROOT / "build"


def ensure_macro_bin() -> pathlib.Path:
    bin_path = BUILD / "macrovm.bin"
    if not bin_path.exists():
        print("[tinyvm] macrovm.bin missing; running build first...")
        subprocess.check_call([sys.executable, str(ROOT / "tools" / "build.py")])
    return bin_path


def compile_user(src: pathlib.Path, out: pathlib.Path):
    subprocess.check_call(
        [sys.executable, str(COMPILER), str(src), str(out)],
        stdout=subprocess.DEVNULL,
    )


_RUNNER_TEMPLATE = """--!nocheck
local micro = require("./_tinyvm")
local D     = require("./_input")

local userEnv = setmetatable({}, {__index=_G})
userEnv._G = userEnv

micro(D, userEnv, %LABEL%)
"""


def cmd_run(args):
    macro_bin = ensure_macro_bin()
    src = pathlib.Path(args.source)
    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr); sys.exit(2)
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        ubin = td / "user.bin"
        compile_user(src, ubin)

        # Combined input module, staged next to the runner.
        input_mod = BUILD / "_input.luau"
        subprocess.check_call(
            [sys.executable, str(PREDEC), str(macro_bin), str(input_mod),
             "--for-micro", "--user", str(ubin)],
            stdout=subprocess.DEVNULL,
        )
        tinyvm_copy = BUILD / "_tinyvm.luau"
        tinyvm_copy.write_text(
            (SRC / "tinyvm.luau").read_text(encoding="latin-1"),
            encoding="latin-1", newline="",
        )

        runner = BUILD / "_runner.luau"
        runner.write_text(
            _RUNNER_TEMPLATE.replace("%LABEL%", repr(args.label)),
            encoding="utf-8",
        )
        try:
            subprocess.check_call(["luau", str(runner)])
        finally:
            for p in (runner, input_mod, tinyvm_copy):
                if p.exists(): p.unlink()


def cmd_compile(args):
    src = pathlib.Path(args.source)
    out = pathlib.Path(args.output)
    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr); sys.exit(2)
    compile_user(src, out)
    print(f"compiled {src} -> {out} ({out.stat().st_size} bytes)")


def main():
    ap = argparse.ArgumentParser(prog="tinyvm")
    sub = ap.add_subparsers(dest="cmd", required=True)

    apr = sub.add_parser("run", help="compile and run a Luau source file")
    apr.add_argument("source")
    apr.add_argument("--label", default="user.luau",
                     help="chunk label shown in diagnostic messages")
    apr.set_defaults(fn=cmd_run)

    apc = sub.add_parser("compile", help="compile a Luau source file to bytecode")
    apc.add_argument("source")
    apc.add_argument("output")
    apc.set_defaults(fn=cmd_compile)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
