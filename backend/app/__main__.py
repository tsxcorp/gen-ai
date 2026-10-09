"""python -m app [--lan] [--port 8000] [--demo]"""
from __future__ import annotations

import argparse
import os


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m app")
    ap.add_argument("--lan", action="store_true", help="bind 0.0.0.0 and require a random access token")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    ap.add_argument("--demo", action="store_true", help="same as AIGEN_DEMO=1")
    args = ap.parse_args()
    if args.lan:
        os.environ["AIGEN_LAN"] = "1"
    if args.demo:
        os.environ["AIGEN_DEMO"] = "1"
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0" if args.lan else "127.0.0.1", port=args.port,
                timeout_graceful_shutdown=2)


if __name__ == "__main__":
    main()
