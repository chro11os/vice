from pathlib import Path

# ~/Library is 0700, so the socket inside is private to this user.
RUNTIME_DIR = Path.home() / "Library" / "Application Support" / "vice"
