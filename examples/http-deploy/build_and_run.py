#!/usr/bin/env python3
"""End-to-end driver for the http-deploy example.

What this demonstrates:
    a launcher that fetches the combined macro-VM + user-program AST
    from a real HTTP server at runtime, decodes the JSON response, and
    runs the user program through the micro-VM.

Steps:
    1. Make sure build/macrovm.bin exists (build it if not).
    2. Compile user.luau -> user.bin, then predecode together with the
       macro-VM into a combined JSON document `payload.json`.
    3. Start a tiny HTTP server (server.py) serving the payload.
    4. Verify the server with a real GET request and capture the body.
    5. Stage:
         staged/tinyvm.luau     - copy of src/tinyvm.luau
         staged/jsondec.luau    - copy of ../jsondec.luau (the parser)
         staged/launcher.luau   - copy of ../launcher.luau
         staged/httpget.luau    - HTTP-GET shim; in this standalone
                                  test it returns the pre-fetched body
                                  because `luau` has no network stack.
                                  In Roblox you'd swap this for one
                                  that calls HttpService:GetAsync(url).
         staged/config.luau     - returns {payloadUrl=..., serverInfo=...}
    6. Run `luau staged/launcher.luau`. The launcher does
            local body = httpGet(config.payloadUrl)
            local data = decode(body)
            micro(data, userEnv, "user.luau")
       The server keeps running for the duration of the run; you can
       curl payload.json yourself while it's up.

This mirrors a real Roblox deployment: the user's compiled program is
hosted on a backend; the deployed Roblox script is just the launcher
that fetches it on demand.
"""
from __future__ import annotations
import sys, pathlib, subprocess, shutil, tempfile, time
import urllib.request

HERE   = pathlib.Path(__file__).resolve().parent
ROOT   = HERE.parents[1]
TOOLS  = ROOT / "tools"
SRC    = ROOT / "src"
BUILD  = ROOT / "build"
STAGED = HERE / "staged"

# Load the in-tree server module without polluting sys.path globally.
sys.path.insert(0, str(HERE))
import server as http_server  # type: ignore
sys.path.pop(0)


def info(msg: str) -> None:
    print(f"[http-deploy] {msg}", flush=True)


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


def luau_quote(s: str) -> str:
    """Quote a string as a Luau long-bracket literal."""
    level = ""
    while ("[" + level + "[") in s or ("]" + level + "]") in s:
        level += "="
    return f"[{level}[{s}]{level}]"


def stage_luau_files(payload_url: str, body: bytes, server_info: str) -> None:
    """Lay out the Luau-side modules next to payload.json in staged/.

    Caller must have already written staged/payload.json before
    invoking this (the server is serving it).
    """
    # 1. Stage the micro-VM, the JSON decoder, and the launcher itself.
    shutil.copy(SRC / "tinyvm.luau",          STAGED / "tinyvm.luau")
    shutil.copy(HERE.parent / "json-deploy" / "jsondec.luau",
                STAGED / "jsondec.luau")
    shutil.copy(HERE / "launcher.luau",       STAGED / "launcher.luau")
    info(f"staged tinyvm.luau ({(SRC/'tinyvm.luau').stat().st_size} bytes), "
         "jsondec.luau, launcher.luau")

    # 2. Generate the httpget shim. In standalone `luau` we can't make
    #    real network calls, so the shim returns the pre-fetched body
    #    whenever the launcher asks for the configured URL.
    body_text = body.decode("utf-8")
    httpget_src = (
        "--!nocheck\n"
        "-- HTTP-GET shim used by the http-deploy example launcher.\n"
        "--\n"
        "-- In Roblox you would write:\n"
        "--   local HttpService = game:GetService('HttpService')\n"
        "--   return function(url) return HttpService:GetAsync(url) end\n"
        "--\n"
        "-- In this standalone luau test the network stack isn't available,\n"
        "-- so we return the body pre-fetched by the build driver.\n"
        f"local _expectedUrl = {luau_quote(payload_url)}\n"
        f"local _body = {luau_quote(body_text)}\n"
        "return function(url)\n"
        "    if url == _expectedUrl then return _body end\n"
        "    error(\"httpget shim: unexpected URL \" .. tostring(url), 0)\n"
        "end\n"
    )
    (STAGED / "httpget.luau").write_text(httpget_src, encoding="utf-8")
    info(f"staged httpget.luau ({len(httpget_src)} chars)")

    # 3. Generate the config module the launcher reads.
    config_src = (
        "--!nocheck\n"
        "-- Configuration the http-deploy launcher reads.\n"
        "return {\n"
        f"    payloadUrl = {luau_quote(payload_url)},\n"
        f"    serverInfo = {luau_quote(server_info)},\n"
        "}\n"
    )
    (STAGED / "config.luau").write_text(config_src, encoding="utf-8")
    info(f"staged config.luau ({len(config_src)} chars)")


def build_payload() -> pathlib.Path:
    """Compile + predecode user.luau together with the macro-VM.

    Wipes and recreates staged/ since we own the directory.
    """
    if STAGED.exists():
        shutil.rmtree(STAGED)
    STAGED.mkdir()
    macro_bin = ensure_macro_bin()
    payload_path = STAGED / "payload.json"
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        user_bin = td / "user.bin"
        compile_user(HERE / "user.luau", user_bin)
        predecode_combined(macro_bin, user_bin, payload_path)
    info(f"built combined payload -> {payload_path.name} "
         f"({payload_path.stat().st_size} bytes)")
    return payload_path


def main():
    # 1. Compile + predecode user.luau together with the macro-VM into a
    #    single payload.json in staged/.
    payload_path = build_payload()

    # 2. Start the HTTP server on a free port.
    httpd, base_url, _thread = http_server.start(payload_path)
    payload_url = f"{base_url}/payload.json"
    server_info = httpd.server_address
    info(f"server up at {base_url} (serving {payload_path.name})")

    try:
        # 3. Do a *real* HTTP GET to verify the server is reachable.
        #    We capture the body so we can also embed it in the
        #    standalone-luau shim; the URL really is being served.
        time.sleep(0.05)  # tiny grace period
        info(f"GET {payload_url}")
        with urllib.request.urlopen(payload_url, timeout=5) as resp:
            body = resp.read()
            server_header = resp.headers.get("Server", "")
        info(f"  HTTP 200, {len(body)} bytes "
             f"(Server: {server_header})")

        # 4. Stage the Luau files with the URL and pre-fetched body baked
        #    into the httpget shim. payload.json stays in staged/ so a
        #    curious user can still curl it while the server's running.
        stage_luau_files(payload_url, body, server_header or "unknown")

        # 5. Run the launcher.
        info("invoking luau on staged/launcher.luau")
        print("=" * 60, flush=True)
        subprocess.check_call(["luau", str(STAGED / "launcher.luau")])
        print("=" * 60, flush=True)
        info("done")
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main()
