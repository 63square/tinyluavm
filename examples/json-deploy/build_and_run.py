#!/usr/bin/env python3
"""End-to-end driver for the json-deploy example.

This example demonstrates a fully JSON-encodable input plane to tinyvm:
the macro-VM AST and the user program are pre-decoded into a single
combined JSON document. The launcher decodes that one document with a
tiny Lua JSON parser and hands the resulting table to the micro-VM as
its `inputData` argument.

Steps:
  1. Make sure build/macrovm.bin exists (build it if not).
  2. Compile user.luau          -> user.bin
  3. Predecode them together    -> staged/payload.json
                                   shape: {"m":[K,F], "u":[K,F]}
  4. Wrap the JSON payload in a Luau module returning it as a string
                                -> staged/payload-json.luau
  5. Copy src/tinyvm.luau, jsondec.luau, launcher.luau to staged/.
  6. Run `luau staged/launcher.luau`.
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


def predecode_combined(macro_bin: pathlib.Path, user_bin: pathlib.Path,
                        out_json: pathlib.Path) -> None:
    """Predecode macro-VM + user code into a single combined JSON payload."""
    subprocess.check_call(
        [sys.executable, str(TOOLS / "predecode.py"),
         str(macro_bin), str(out_json),
         "--for-micro", "--json", "--user", str(user_bin)],
        stdout=subprocess.DEVNULL,
    )


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

    # 1. Make sure the compiled macro-VM bytecode exists.
    macro_bin = ensure_macro_bin()

    # 2. Compile the user program; immediately predecode with the macro-VM
    #    into a single combined payload.
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        user_bin = td / "user.bin"
        compile_user(HERE / "user.luau", user_bin)
        payload_json = STAGED / "payload.json"
        predecode_combined(macro_bin, user_bin, payload_json)
        info(f"predecoded macro-VM + user.luau -> payload.json "
             f"({payload_json.stat().st_size} bytes)")

    # 3. Wrap the JSON document in a Luau module so the launcher can
    #    `require()` it. Replace this in a real deployment with whatever
    #    channel makes sense (HttpService:GetAsync, an asset, etc.).
    wrap_json_as_module(payload_json, STAGED / "payload-json.luau")
    payload_json.unlink()
    info("wrapped JSON payload as a Luau module")

    # 4. Stage the micro-VM source, the JSON decoder, and the launcher.
    shutil.copy(SRC / "tinyvm.luau",    STAGED / "tinyvm.luau")
    shutil.copy(HERE / "jsondec.luau",  STAGED / "jsondec.luau")
    shutil.copy(HERE / "launcher.luau", STAGED / "launcher.luau")
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
