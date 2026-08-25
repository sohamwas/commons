"""Run the Commons proxy.

    .venv/Scripts/python.exe scripts/run_proxy.py
"""

from __future__ import annotations

import logging

import uvicorn

from commons.proxy.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)-28s %(message)s",
    datefmt="%H:%M:%S",
)

if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=8787, log_level="warning")
