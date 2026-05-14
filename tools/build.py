#!/usr/bin/env python3
"""Build pipeline for tinyvm.

Outputs in ./build/:
  macrovm.bin            - compiled macro-VM bytecode (for reference).
  macrovm-ast.luau       - pre-decoded macro-VM (`return {K, F}`) for
                           consumption by the micro-VM.

Usage:
    python tools/build.py
"""
from __future__ import annotations
import sys, pathlib, subprocess, argparse

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
BUILD = ROOT / "build"
COMPILER = ROOT / "tools" / "compiler.py"
PREDEC = ROOT / "tools" / "predecode.py"


def build_macro_bin() -> bytes:
    BUILD.mkdir(exist_ok=True)
    out = BUILD / "macrovm.bin"
    subprocess.check_call(
        [sys.executable, str(COMPILER), str(SRC / "macrovm.luau"), str(out)]
    )
    data = out.read_bytes()
    print(f"  macrovm.bin: {len(data)} bytes")
    return data


def predecode_macro() -> pathlib.Path:
    out = BUILD / "macrovm-ast.luau"
    subprocess.check_call(
        [sys.executable, str(PREDEC), str(BUILD / "macrovm.bin"), str(out),
         "--for-micro"]
    )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.parse_args()
    print("Building tinyvm artifacts...")
    build_macro_bin()
    out = predecode_macro()
    print(f"  macrovm-ast.luau: {out.stat().st_size} bytes")
    print()
    print(f"src/tinyvm.luau (micro-VM source):  {(SRC/'tinyvm.luau').stat().st_size} bytes")
    print(f"src/macrovm.luau (macro-VM source): {(SRC/'macrovm.luau').stat().st_size} bytes")


if __name__ == "__main__":
    main()
