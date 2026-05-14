#!/usr/bin/env python3
"""End-to-end driver for the json-deploy example.

This example demonstrates a fully JSON-encodable input plane to tinyvm:
both the macro-VM AST and the user program are pre-decoded to JSON before
launch. The launcher decodes them with a tiny Lua JSON parser and hands
the resulting tables to the micro-VM.

Steps:
  1. Make sure build/macrovm.bin exists (build it if not).
  2. Predecode build/macrovm.bin -> staged/macrovm-ast.json (--for-micro).
  3. Compile user.luau               -> user.bin
  4. Predecode user.bin              -> staged/user-ast.json (no --for-micro)
  5. Wrap each JSON file in a Luau module returning it as a string.
  6. Copy src/tinyvm.luau, jsondec.luau, launcher.luau to staged/.
  7. Run `luau staged/launcher.luau`.
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
    print(f"[json-deploy] {msg}", flush=True)


def ensure_macro_bin() -> pathlib.Path:
    bin_path = BUILD / "macrovm.bin"
    if not bin_path.exists():
        info("macrovm.bin missing -- running tools/build.py")
        subprocess.check_call(
            [sys.executable, str(TOOLS / "build.py")],
            stdout=subprocess.DEVNULL,
        )
    return bin_path


def predecode_to_json(in_bin: pathlib.Path, out_json: pathlib.Path,
                       for_micro: bool) -> None:
    args = [sys.executable, str(TOOLS / "predecode.py"),
            str(in_bin), str(out_json), "--json"]
    if for_micro:
        args.append("--for-micro")
    subprocess.check_call(args, stdout=subprocess.DEVNULL)


def compile_user(src: pathlib.Path, out: pathlib.Path) -> None:
    subprocess.check_call(
        [sys.executable, str(TOOLS / "compiler.py"), str(src), str(out)],
        stdout=subprocess.DEVNULL,
    )


def _long_bracket_level(s: str) -> str:
    """Pick a Lua long-bracket level that doesn't collide with the content."""
    level = ""
    while ("[" + level + "[") in s or ("]" + level + "]") in s:
        level += "="
    return level


def wrap_json_as_module(json_path: pathlib.Path, out_path: pathlib.Path) -> None:
    """Wrap a JSON string in a Luau module returning {jsonText}.

    Standalone `luau` (and Roblox) require module returns to be a table
    or function, not a bare string, so we wrap in a single-element table.
    """
    text = json_path.read_text(encoding="utf-8")
    level = _long_bracket_level(text)
    body = f"[{level}[{text}]{level}]"
    out_path.write_text(
        "--!nocheck\n"
        f"-- JSON payload from {json_path.name} ({len(text)} chars).\n"
        f"return {{{body}}}\n",
        encoding="utf-8",
    )


def stage():
    if STAGED.exists():
        shutil.rmtree(STAGED)
    STAGED.mkdir()

    # 1. Compile + predecode the macro-VM (uses --for-micro: the micro-VM-
    #    specific atom rewrites apply because the *micro-VM* will consume it).
    macro_bin = ensure_macro_bin()
    macro_json = STAGED / "macrovm-ast.json"
    predecode_to_json(macro_bin, macro_json, for_micro=True)
    info(f"predecoded macro-VM -> {macro_json.name} "
         f"({macro_json.stat().st_size} bytes)")

    # 2. Compile + predecode the user program (no --for-micro: the *macro-VM*
    #    consumes it at runtime, so we only apply rewrites the macro-VM
    #    supports).
    user_bin = STAGED / "user.bin"
    compile_user(HERE / "user.luau", user_bin)
    user_json = STAGED / "user-ast.json"
    predecode_to_json(user_bin, user_json, for_micro=False)
    info(f"predecoded user.luau -> {user_json.name} "
         f"({user_json.stat().st_size} bytes)")
    user_bin.unlink()

    # 3. Wrap each JSON file in a Luau module the launcher can require().
    wrap_json_as_module(macro_json, STAGED / "macrovm-ast-json.luau")
    wrap_json_as_module(user_json,  STAGED / "user-ast-json.luau")
    macro_json.unlink()
    user_json.unlink()
    info("wrapped JSON payloads as Luau modules")

    # 4. Stage the micro-VM source, the JSON decoder, and the launcher.
    shutil.copy(SRC / "tinyvm.luau",        STAGED / "tinyvm.luau")
    shutil.copy(HERE / "jsondec.luau",      STAGED / "jsondec.luau")
    shutil.copy(HERE / "launcher.luau",     STAGED / "launcher.luau")
    info(f"staged tinyvm.luau ({(SRC/'tinyvm.luau').stat().st_size} bytes), "
         f"jsondec.luau, launcher.luau")


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
