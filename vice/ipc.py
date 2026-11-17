"""Newline-delimited JSON over a Unix socket. One request line in, one response line out."""
import asyncio
import json
import os
import socket

from .platform import RUNTIME_DIR

SOCKET_PATH = RUNTIME_DIR / "vice.sock"
LOCK_PATH = RUNTIME_DIR / "vice.lock"


def request(cmd: str, timeout: float = 2.0) -> dict:
    """Client side, used by the `vice` CLI. Raises ConnectionError if no daemon is running."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(SOCKET_PATH))
            s.sendall(json.dumps({"cmd": cmd}).encode() + b"\n")
            return json.loads(s.makefile().readline())
    except (FileNotFoundError, ConnectionRefusedError) as e:
        raise ConnectionError("vice daemon is not running") from e


async def serve(handler) -> asyncio.Server:
    """Server side. `handler(dict) -> dict` is called once per request line."""
    async def on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            while line := await reader.readline():
                try:
                    req = json.loads(line)
                    if not isinstance(req, dict):
                        raise ValueError("request must be a JSON object")
                except ValueError as e:
                    resp = {"ok": False, "error": f"bad request: {e}"}
                else:
                    resp = await handler(req)
                writer.write(json.dumps(resp).encode() + b"\n")
                await writer.drain()
        finally:
            writer.close()

    server = await asyncio.start_unix_server(on_client, path=str(SOCKET_PATH))
    os.chmod(SOCKET_PATH, 0o600)  # trust boundary: later this socket can trigger tools
    return server
