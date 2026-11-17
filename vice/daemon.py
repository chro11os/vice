import asyncio
import fcntl
import os
import signal
import time

from . import config, ipc, sounds


class Daemon:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.state = "idle"
        self.started = time.monotonic()
        self.stop = asyncio.Event()

    def cue(self, name: str) -> None:
        if self.cfg["sounds"]:
            sounds.play(name)

    async def handle(self, req: dict) -> dict:
        """Answer one IPC request. Every response has "ok"; failures carry "error"."""
        match req.get("cmd"):
            case "status":
                return {"ok": True, "state": self.state, "pid": os.getpid(),
                        "uptime_s": round(time.monotonic() - self.started, 1)}
            case "quit":
                self.stop.set()
                return {"ok": True}
            case other:
                return {"ok": False, "error": f"unknown command: {other!r}"}


def _acquire_lock():
    """Single instance via flock: the kernel releases it if we crash, so no stale-lock cleanup."""
    ipc.RUNTIME_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = open(ipc.LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("vice: already running")
    return lock  # caller must keep this object alive, or the lock is released


async def run() -> None:
    lock = _acquire_lock()
    ipc.SOCKET_PATH.unlink(missing_ok=True)  # safe: we hold the lock, so any socket file is stale

    daemon = Daemon(config.load())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):  # SIGTERM = what launchd/systemd send on stop
        loop.add_signal_handler(sig, daemon.stop.set)

    server = await ipc.serve(daemon.handle)
    print(f"vice: listening on {ipc.SOCKET_PATH}", flush=True)
    daemon.cue("start")

    async with server:
        await daemon.stop.wait()

    daemon.cue("stop")
    await asyncio.sleep(0.15)  # let the stop chime finish before the process exits
    ipc.SOCKET_PATH.unlink(missing_ok=True)
    lock.close()
    print("vice: stopped", flush=True)
