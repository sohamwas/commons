"""Run the Commons proxy.

    .venv/Scripts/python.exe scripts/run_proxy.py                      # OBSERVE
    .venv/Scripts/python.exe scripts/run_proxy.py --mode ENFORCE
    .venv/Scripts/python.exe scripts/run_proxy.py --mode ENFORCE --db enforce.db

Every flag also reads an environment variable, because the container has no command line
to edit. The flag wins where both are given.

--host DEFAULTS TO LOOPBACK AND SHOULD STAY THERE outside a container. Commons sees
payment amounts, customer identifiers and refund decisions, and binding it to 0.0.0.0 on
a laptop publishes all of that to the local network. The Docker image sets 0.0.0.0
because a container's loopback reaches nothing else, and compose publishes the port back
to 127.0.0.1 on the host so the exposure is the same either way.
"""

from __future__ import annotations

import argparse
import logging
import os

import uvicorn

from commons.proxy.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)-28s %(message)s",
    datefmt="%H:%M:%S",
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["OBSERVE", "ENFORCE"],
        default=os.environ.get("COMMONS_MODE", "OBSERVE"),
    )
    parser.add_argument("--db", default=os.environ.get("COMMONS_DB", "commons.db"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("COMMONS_PORT", "8787"))
    )
    parser.add_argument("--host", default=os.environ.get("COMMONS_HOST", "127.0.0.1"))
    parser.add_argument(
        "--agents", default=os.environ.get("COMMONS_AGENTS", "agents.yaml")
    )
    parser.add_argument(
        "--vendors", default=os.environ.get("COMMONS_VENDORS", "vendors.yaml")
    )
    args = parser.parse_args()

    uvicorn.run(
        create_app(
            db_path=args.db,
            mode=args.mode,
            agents_path=args.agents,
            vendors_path=args.vendors,
        ),
        host=args.host,
        port=args.port,
        log_level="warning",
    )
