#!/usr/bin/env python3
"""Tiny single-route HTTP server used by the http-deploy example.

Serves one URL: `GET /payload.json`. Imported by `build_and_run.py`
as a thread; runnable standalone with `python server.py` for manual
poking with `curl`.
"""
from __future__ import annotations
import http.server
import json
import socketserver
import threading
import pathlib


class _Handler(http.server.BaseHTTPRequestHandler):
    payload_path: pathlib.Path = None  # set by start()
    server_info: str = "tinyvm-http-deploy/1.0"

    # Silence the default access-log spam.
    def log_message(self, fmt, *args):  # noqa: N802
        return

    def do_GET(self):  # noqa: N802
        if self.path in ("/payload.json", "/payload.json/"):
            data = self.payload_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Server", self.server_info)
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path in ("/", "/index"):
            body = (
                "<html><body>"
                "<h1>tinyvm-http-deploy</h1>"
                "<p>The example payload lives at "
                "<a href='/payload.json'>/payload.json</a>.</p>"
                "</body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404, f"unknown path {self.path}")


def start(payload_path: pathlib.Path, host: str = "127.0.0.1",
          port: int = 0) -> tuple[socketserver.TCPServer, str, threading.Thread]:
    """Spin up the server in a daemon thread.

    Returns the bound `(server, base_url, thread)` so the caller can
    shut it down. Pass `port=0` to let the OS pick a free port.
    """
    handler = type("Handler", (_Handler,), {
        "payload_path": payload_path,
    })

    httpd = socketserver.TCPServer((host, port), handler)
    bound_host, bound_port = httpd.server_address[:2]
    base_url = f"http://{bound_host}:{bound_port}"

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, base_url, thread


def main():
    """CLI entry point: serve a payload.json from the current dir on 8080."""
    import argparse, time, sys
    ap = argparse.ArgumentParser()
    ap.add_argument("payload", help="path to payload.json")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    payload = pathlib.Path(args.payload)
    if not payload.exists():
        print(f"error: {payload} not found", file=sys.stderr)
        sys.exit(2)
    httpd, url, _ = start(payload, args.host, args.port)
    print(f"serving {payload} -> {url}/payload.json (Ctrl+C to stop)")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        httpd.shutdown()
        print("\nstopped")


if __name__ == "__main__":
    main()
