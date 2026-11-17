import argparse
import asyncio
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="vice")
    parser.add_argument("cmd", nargs="?", default="run", choices=["run", "status", "quit"])
    cmd = parser.parse_args().cmd

    if cmd == "run":
        from . import daemon  # imported lazily so CLI commands don't load numpy/PortAudio
        asyncio.run(daemon.run())
        return

    from . import ipc
    try:
        resp = ipc.request(cmd)
    except ConnectionError as e:
        sys.exit(f"vice: {e}")
    print(json.dumps(resp, indent=2))
    sys.exit(0 if resp.get("ok") else 1)


if __name__ == "__main__":
    main()
