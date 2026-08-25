"""Run the Commons proxy.

    .venv/Scripts/python.exe scripts/run_proxy.py                      # OBSERVE
    .venv/Scripts/python.exe scripts/run_proxy.py --mode ENFORCE
    .venv/Scripts/python.exe scripts/run_proxy.py --mode ENFORCE --db enforce.db
"""

from __future__ import annotations

import argparse
import logging

import uvicorn

from commons.proxy.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)-28s %(message)s",
    datefmt="%H:%M:%S",
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["OBSERVE", "ENFORCE"], default="OBSERVE")
    parser.add_argument("--db", default="commons.db")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    uvicorn.run(
        create_app(db_path=args.db, mode=args.mode),
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
    )
