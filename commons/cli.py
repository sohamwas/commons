"""Commons CLI.

    commons world --seed 4471 --days 30        # print the world's event timeline
"""

from __future__ import annotations

import argparse
import json
import sys

from commons.world.world import build_world


def cmd_world(args: argparse.Namespace) -> int:
    world = build_world(
        seed=args.seed,
        n_customers=args.customers,
        days=args.days,
        overlap_rate=args.overlap_rate,
    )
    events = world.generate()

    if args.json:
        print(
            json.dumps(
                {
                    "summary": world.summary(),
                    "events": [
                        {
                            "at": e.at.isoformat(),
                            "seq": e.seq,
                            "type": str(e.type),
                            "customer_id": e.customer_id,
                            "payload": e.payload,
                        }
                        for e in events
                    ],
                },
                indent=2,
            )
        )
        return 0

    summary = world.summary()
    print(f"seed={summary['seed']}  customers={summary['customers']}  days={summary['days']}")
    print(
        f"sampled for overlap: {summary['customers_with_2plus_conditions']}"
        f"/{summary['customers']} have 2+ concurrent conditions "
        f"({summary['share_with_2plus_conditions']:.0%})"
    )
    print(f"events: {len(events)}\n")

    for event in events:
        agent = event.type.agent or "-"
        print(f"{event.describe()}   -> {agent}")

    print("\nper-customer condition counts:")
    for c in world.customers.values():
        if c.conditions:
            print(f"  {c.id:<12} {c.name:<12} {', '.join(c.conditions)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="commons")
    sub = parser.add_subparsers(dest="command", required=True)

    world = sub.add_parser("world", help="generate and print a simulated world")
    world.add_argument("--seed", type=int, default=4471)
    world.add_argument("--customers", type=int, default=20)
    world.add_argument("--days", type=int, default=30)
    world.add_argument("--overlap-rate", type=float, default=0.6)
    world.add_argument("--json", action="store_true")
    world.set_defaults(func=cmd_world)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
