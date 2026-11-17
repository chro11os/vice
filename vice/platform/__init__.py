"""The one place that branches on OS. Everything else imports from here."""
import sys

if sys.platform == "darwin":
    from .macos import RUNTIME_DIR
else:
    from .linux import RUNTIME_DIR

__all__ = ["RUNTIME_DIR"]
