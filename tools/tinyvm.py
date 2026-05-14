#!/usr/bin/env python3
"""tinyvm CLI: compile a Luau source file and run it via the tinyvm bundle.

Usage:
    python tools/tinyvm.py run <source.luau> [-- args...]
    python tools/tinyvm.py compile <source.luau> <output.bin>

The `run` subcommand:
    1. Compiles <source.luau> via tools/compiler.py.
    2. Generates a Luau wrapper that loads build/tinyvm-bundled.luau and the
       compiled user bytecode, then invokes it against a default environment.
    3. Executes the wrapper with `luau` (must be on PATH).

The `compile` subcommand just produces the compiled bytecode file; useful
when you want to ship a .bin separately and load it from your own host code.
"""
from __future__ import annotations
import sys, os, pathlib, subprocess, argparse, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPILER = ROOT / "tools" / "compiler.py"
BUILD = ROOT / "build"
BUNDLE = BUILD / "tinyvm-bundled.luau"

def ensure_bundle():
    if not BUNDLE.exists():
        print("[tinyvm] no bundle found; running build first...")
        subprocess.check_call([sys.executable, str(ROOT/"tools"/"build.py")])

def compile_user(src: pathlib.Path, out: pathlib.Path):
    subprocess.check_call([sys.executable, str(COMPILER), str(src), str(out)])

def _hex_lit(data: bytes) -> str:
    return "".join(f"\\x{b:02x}" for b in data)

def cmd_run(args):
    ensure_bundle()
    src = pathlib.Path(args.source)
    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr); sys.exit(2)
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        ubin = td / "user.bin"
        compile_user(src, ubin)
        data = ubin.read_bytes()
        # Build wrapper next to the bundle so the relative require works.
        wrapper = BUILD / "_runner.luau"
        wrapper.write_text(
            "--!nocheck\n"
            "local play = require(\"./tinyvm-bundled\")\n"
            f'local user = "{_hex_lit(data)}"\n'
            "local env = setmetatable({}, {__index=_G})\n"
            "env._G = env\n"
            f"play(user, env, {args.label!r}, ...)\n",
            encoding="utf-8",
        )
        cmd = ["luau", str(wrapper)]
        if args.luau_args:
            cmd.append("-a")
            cmd.extend(args.luau_args)
        subprocess.check_call(cmd)
        wrapper.unlink()

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
    apr.add_argument("luau_args", nargs="*", default=[])
    apr.set_defaults(fn=cmd_run)

    apc = sub.add_parser("compile", help="compile a Luau source file to bytecode")
    apc.add_argument("source")
    apc.add_argument("output")
    apc.set_defaults(fn=cmd_compile)

    args = ap.parse_args()
    args.fn(args)

if __name__ == "__main__":
    main()
