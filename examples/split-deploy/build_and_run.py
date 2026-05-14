#!/usr/bin/env python3
"""End-to-end driver for the split-deploy example.

Walks through what a real consumer of `tinyvm` would do under the
split-deploy story (the README's Option 2):

  1. Build the macro-VM AST     -> build/macrovm-ast.luau          (one-time)
  2. Compile the user program   -> user.bin (temporary)
  3. Predecode the user program -> staged/user-ast.luau
  4. Stage the three modules    -> staged/{tinyvm,macrovm-ast,user-ast}.luau
  5. Run the launcher           -> staged/launcher.luau            (via `luau`)

The "staged" subdirectory is what would correspond, in a Roblox project,
to a folder of ModuleScripts where the launcher and the three modules
all live next to each other. We assemble it freshly on every run so the
example is reproducible.
"""
from __future__ import annotations
import sys, pathlib, subprocess, shutil, tempfile

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
    subprocess.check_call(
        [sys.executable, str(TOOLS / "compiler.py"), str(src), str(out)],
        stdout=subprocess.DEVNULL,
    )


def predecode_user(bin_path: pathlib.Path, out_path: pathlib.Path) -> None:
    """Predecode a user-code .bin into a Luau module returning {K, F}."""
    subprocess.check_call(
        [sys.executable, str(TOOLS / "predecode.py"),
         str(bin_path), str(out_path)],
        stdout=subprocess.DEVNULL,
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

    # 3. Compile and predecode the user program
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        user_bin = td / "user.bin"
        compile_user(HERE / "user.luau", user_bin)
        info(f"compiled user.luau ({user_bin.stat().st_size} bytes of bytecode)")
        user_ast = STAGED / "user-ast.luau"
        predecode_user(user_bin, user_ast)
        info(f"predecoded user.luau -> user-ast.luau "
             f"({user_ast.stat().st_size} bytes)")

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
