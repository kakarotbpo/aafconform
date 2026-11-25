"""Serve the interface to an ordinary browser, for development and UI tests.

The page talks to the same Bridge as the desktop window, over POST /api/<name>.
Listens on 127.0.0.1 only. File dialogs are not available here; paths are
loaded by calling app.load(...) from the page or a test.
"""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .bridge import Bridge

UI = Path(__file__).resolve().parent / "ui"
DEV_FLAG = b"<script>window.AAFCONFORM_DEV = true;</script>"


def make_server(port: int = 0) -> ThreadingHTTPServer:
    bridge = Bridge()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            name = self.path.split("?", 1)[0].lstrip("/") or "index.html"
            target = (UI / name).resolve()
            if UI not in target.parents or not target.is_file():
                self._send(404, b"not found", "text/plain")
                return
            body = target.read_bytes()
            if name == "index.html":
                body = body.replace(b"</head>", DEV_FLAG + b"</head>", 1)
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            self._send(200, body, ctype)

        def do_POST(self):
            name = self.path.removeprefix("/api/")
            method = getattr(bridge, name, None)
            if name.startswith("_") or not callable(method):
                self._send(404, b"{}", "application/json")
                return
            length = int(self.headers.get("Content-Length") or 0)
            args = json.loads(self.rfile.read(length) or b"{}").get("args", [])
            result = method(*args)
            self._send(200, json.dumps(result).encode(), "application/json")

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(port: int = 8765) -> None:
    server = make_server(port)
    print(f"aafconform UI at http://127.0.0.1:{server.server_address[1]}/")
    server.serve_forever()
