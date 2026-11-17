import tomllib
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "vice" / "config.toml"

DEFAULTS = {
    "sounds": True,
    "hold_ms": 300,
}


def load(path: Path = CONFIG_PATH) -> dict:
    """Defaults overlaid with the user's TOML. A missing file is fine; a broken one is not."""
    if not path.exists():
        return dict(DEFAULTS)
    with path.open("rb") as f:
        user = tomllib.load(f)
    unknown = user.keys() - DEFAULTS.keys()
    if unknown:
        raise ValueError(f"{path}: unknown keys {sorted(unknown)}")
    # TODO(human): reject values of the wrong type or out of range before merging.
    # e.g. `hold_ms = "300"` or `hold_ms = -5` or `sounds = "yes"` currently slip through
    # and would only blow up much later, deep inside the hotkey code.
    return DEFAULTS | user
