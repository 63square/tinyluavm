#!/usr/bin/env python3
"""Build pipeline for tinyvm (experimental sub-2k branch).

Outputs in ./build/:
  macrovm.bin              - compiled macro-VM bytecode (for reference).
  macrovm-ast.luau         - pre-decoded macro-VM (K, F) as Lua return expression.
  tinyvm-bundled.luau      - self-contained: micro-VM + AST + op-helpers env.

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
    subprocess.check_call([sys.executable, str(COMPILER), str(SRC/"macrovm.luau"), str(out)])
    data = out.read_bytes()
    print(f"  macrovm.bin: {len(data)} bytes")
    return data

def predecode(rewrite_ops: bool, fold_bool: bool, force_gfor3: bool=False, split_assign: bool=False) -> pathlib.Path:
    out = BUILD / "macrovm-ast.luau"
    args = [sys.executable, str(PREDEC), str(BUILD/"macrovm.bin"), str(out)]
    if rewrite_ops: args.append("--rewrite-ops")
    if fold_bool:   args.append("--fold-bool")
    if force_gfor3: args.append("--force-gfor3")
    if split_assign: args.append("--split-assign")
    subprocess.check_call(args)
    return out

# The shadow env exposing operator helpers and falling through to the user env / _G.
# For now the bundle keeps a thin shim that wraps user env into shadow env at call time.
OP_SETUP = (
    "local function _E(u)return setmetatable({"
    "B1=function(a,b)return a+b end,B2=function(a,b)return a-b end,"
    "B3=function(a,b)return a*b end,B4=function(a,b)return a/b end,"
    "B5=function(a,b)return a//b end,B6=function(a,b)return a%b end,"
    "B7=function(a,b)return a^b end,B8=function(a,b)return a..b end,"
    "B9=function(a,b)return a==b end,B10=function(a,b)return a~=b end,"
    "B11=function(a,b)return a<b end,B12=function(a,b)return a<=b end,"
    "B13=function(a,b)return a>b end,B14=function(a,b)return a>=b end,"
    "U1=function(a)return-a end,U2=function(a)return not a end,"
    "U3=function(a)return#a end},{__index=u}) end\n"
)

def main():
    ap = argparse.ArgumentParser()
    args = ap.parse_args()
    print("Building tinyvm artifacts...")
    build_macro_bin()
    predecode(rewrite_ops=True, fold_bool=True, force_gfor3=True, split_assign=True)
    micro = (SRC / "tinyvm.luau").read_text(encoding="latin-1").rstrip("\n")
    ast = (BUILD / "macrovm-ast.luau").read_text(encoding="latin-1")
    if ast.startswith("--!nocheck\n"): ast = ast[len("--!nocheck\n"):]
    if ast.startswith("return "):      ast = ast[len("return "):]
    ast = ast.rstrip("\n")
    out = BUILD / "tinyvm-bundled.luau"
    # Shadow env wraps the user env so macro-VM globals (string.byte, table.pack,
    # error, etc.) and our op-helpers (B1..B14, U1..U3) resolve correctly while
    # still allowing the user program to see its own env via fallthrough.
    out.write_text(
        "--!nocheck\n"
        "local tp,tu=table.pack,table.unpack\n"
        + OP_SETUP +
        "local _mvm=(function()\n" + micro + "\nend)()\n"
        f"local _K,_F={ast}\n"
        "return function(b,e,...) return _mvm(_K,_F,_E(e),tp,tu,b,e,...) end\n",
        encoding="latin-1", newline="",
    )
    print(f"  tinyvm-bundled.luau: {out.stat().st_size} bytes")
    print(f"\nsrc/tinyvm.luau (micro-VM source):  {(SRC/'tinyvm.luau').stat().st_size} bytes")
    print(f"src/macrovm.luau (macro-VM source): {(SRC/'macrovm.luau').stat().st_size} bytes")

if __name__ == "__main__":
    main()
