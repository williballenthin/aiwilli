from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote


class MarginHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def build_review_url(host: str, port: int, artifact_name: str) -> str:
    """Build the browser URL for a served review artifact.

    Args:
        host: Listening host.
        port: Listening port.
        artifact_name: Artifact filename relative to the served directory.
    """
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{browser_host}:{port}/{quote(artifact_name)}"


def create_http_server(root: Path, host: str, port: int) -> MarginHTTPServer:
    """Create an HTTP server rooted at a directory.

    Args:
        root: Directory to serve.
        host: Listening host.
        port: Listening port.
    """
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    return MarginHTTPServer((host, port), handler)


def start_http_server(
    root: Path,
    host: str,
    port: int,
) -> tuple[MarginHTTPServer, threading.Thread, int]:
    """Start an HTTP server in a background thread.

    Args:
        root: Directory to serve.
        host: Listening host.
        port: Requested listening port. `0` lets the OS choose.
    """
    server = create_http_server(root, host=host, port=port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    actual_port = int(server.server_address[1])
    return server, thread, actual_port


def run_http_server(root: Path, host: str, port: int) -> None:
    """Serve a directory until interrupted.

    Args:
        root: Directory to serve.
        host: Listening host.
        port: Listening port.
    """
    server = create_http_server(root, host=host, port=port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
