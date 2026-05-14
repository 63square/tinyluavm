#!/usr/bin/env python3
"""End-to-end driver for the split-deploy example.

Walks through what a real consumer of `tinyvm` would do under the
split-deploy (Option 2 in the README) story:

  1. Build the macro-VM AST     -> build/macrovm-ast.luau    (one-time)
  2. Compile the user program   -> staged/user.bin
  3. Embed the bytecode as hex  -> staged/user_bytecode.luau
  4. Stage the three modules    -> staged/{tinyvm,macrovm-ast,user_bytecode}.luau
  5. Run the launcher           -> staged/launcher.luau   (via `luau`)

The "staged" subdirectory is what would correspond, in a Roblox project,
to a folder of ModuleScripts where the launcher and the three modules
all live next to each other. We assemble it freshly on every run so the
example is reproducible.
"""
from __future__ import annotations
import sys, pathlib, subprocess, shutil

HERE   = pathlib.Path(__file__).resolve().parent
ROOT   = HERE.parents[1]
TOOLS  = ROOT / "tools"
SRC    = ROOT / "src"
BUILD  = ROOT / "build"
STAGED = HERE / "staged"


def info(msg: str) -> None:
    print(f"[split-deploy] {msg}", flush=True)


def ensure_ast() -> pathlib.Path:
    """Make sure build/macrovm-ast.luau exists; build it if not."""
    ast = BUILD / "macrovm-ast.luau"
    if not ast.exists():
        info("macrovm-ast.luau missing -- running tools/build.py")
        subprocess.check_call(
            [sys.executable, str(TOOLS / "build.py")],
            stdout=subprocess.DEVNULL,
        )
    return ast


def compile_user(src: pathlib.Path, out: pathlib.Path) -> None:
    """Compile a .luau file to our bytecode format."""
    subprocess.check_call(
        [sys.executable, str(TOOLS / "compiler.py"), str(src), str(out)],
        stdout=subprocess.DEVNULL,
    )


def make_hex_module(bin_path: pathlib.Path, out: pathlib.Path) -> None:
    """Write a Luau module that returns the .bin contents as a hex string.

    Wrapped in a single-element table so it's a require()-able module.
    Standalone `luau` rejects modules whose body returns a bare string.
    """
    data = bin_path.read_bytes()
    hex_lit = "".join(f"{b:02x}" for b in data)
    # Wrap to ~76 chars/line for readability.
    chunks = [hex_lit[i:i + 76] for i in range(0, len(hex_lit), 76)]
    body = '"' + '" ..\n  "'.join(chunks) + '"'
    out.write_text(
        "--!nocheck\n"
        "-- Compiled user bytecode (hex-encoded). Wrapped in a table so\n"
        "-- `require()` accepts it as a module return.\n"
        f"-- Original size: {len(data)} bytes.\n"
        f"return {{\n  {body}\n}}\n",
        encoding="utf-8",
    )


def stage():
    """Set up examples/split-deploy/staged/ with the four required modules."""
    if STAGED.exists():
        shutil.rmtree(STAGED)
    STAGED.mkdir()

    # 1. The micro-VM
    shutil.copy(SRC / "tinyvm.luau", STAGED / "tinyvm.luau")
    info(f"staged tinyvm.luau ({(SRC/'tinyvm.luau').stat().st_size} bytes)")

    # 2. The predecoded macro-VM AST
    ast = ensure_ast()
    shutil.copy(ast, STAGED / "macrovm-ast.luau")
    info(f"staged macrovm-ast.luau ({ast.stat().st_size} bytes)")

    # 3. Compile the user program and embed it as a hex module
    user_src = HERE / "user.luau"
    user_bin = STAGED / "user.bin"
    compile_user(user_src, user_bin)
    info(f"compiled user.luau ({user_bin.stat().st_size} bytes of bytecode)")

    hex_mod = STAGED / "user_bytecode.luau"
    make_hex_module(user_bin, hex_mod)
    info(f"staged user_bytecode.luau ({hex_mod.stat().st_size} bytes)")
    user_bin.unlink()

    # 4. The launcher
    shutil.copy(HERE / "launcher.luau", STAGED / "launcher.luau")
    info("staged launcher.luau")


def run():
    info("invoking luau on staged/launcher.luau")
    print("=" * 60, flush=True)
    subprocess.check_call(["luau", str(STAGED / "launcher.luau")])
    print("=" * 60, flush=True)
    info("done")


def main():
    stage()
    run()


if __name__ == "__main__":
    main()
