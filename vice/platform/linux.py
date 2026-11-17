import os
from pathlib import Path

# $XDG_RUNTIME_DIR is a per-user 0700 tmpfs that systemd wipes on logout.
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/tmp/vice-{os.getuid()}")) / "vice"
