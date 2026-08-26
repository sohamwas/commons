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


def cmd_run(args: argparse.Namespace) -> int:
    import logging

    from commons.runner import run_sync, write_report

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    report = run_sync(
        seed=args.seed,
        mode=args.mode,
        days=args.days,
        customers=args.customers,
        limit=args.limit,
        db=args.db,
    )

    print("\n" + "=" * 72)
    print(f"RUN COMPLETE  seed={report.seed}  mode={report.mode}  days={report.days}")
    print("=" * 72)
    ws = report.world_summary
    print(
        f"world: {ws['customers']} customers, {report.events} events, "
        f"{ws['customers_with_2plus_conditions']} with 2+ concurrent conditions "
        f"({ws['share_with_2plus_conditions']:.0%} — sampled deliberately)"
    )

    led = report.ledger
    print(f"\ntool calls through Commons: {led['calls']}  (forwarded: {led['forwarded']})")
    print(f"decisions: {led['by_decision']}")
    print(f"violations by rule:")
    for rule, count in sorted(led["violations_by_rule"].items(), key=lambda kv: -kv[1]):
        print(f"    {rule:<32} {count}")
    print(f"customers affected by a violation: {led['customers_affected']}")
    print(f"total discount delivered: {led['total_discount_delivered_pct']:g}%")
    print(
        f"\nCONVERGENCE (the exposure, whether or not a threshold broke):"
        f"\n    customers worked by 2+ agents:        {led['customers_touched_by_multiple_agents']}"
        f"\n    discounted by 2+ agents:              {led['customers_discounted_by_multiple_agents']}"
        f"\n    sitting AT or OVER the 15% cap:       {led['customers_at_or_over_discount_cap']}"
        f"\n    direct contradictions detected:       {led['contradictions_detected']}"
        f"  (one agent restricting who another incentivises)"
    )

    reactions = {}
    for r in report.reactions:
        reactions[r["reaction"]] = reactions.get(r["reaction"], 0) + 1
    print(f"\ncustomer reactions: {reactions or 'none'}")

    print(
        f"\nmalformed tool calls: {report.malformed_tool_calls}  "
        f"(counted separately from violations)"
    )
    print(
        f"duplicate tool calls dropped: {report.duplicate_tool_calls}  "
        f"(same tool repeated for one event)"
    )
    print(f"agent errors: {report.agent_errors}")
    print(f"llm: {report.llm}")

    if args.out:
        write_report(report, args.out)
        print(f"\nreport written: {args.out}")
    return 0


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _count_reactions(report: dict) -> dict:
    counts: dict[str, int] = {}
    for r in report.get("reactions", []):
        counts[r["reaction"]] = counts.get(r["reaction"], 0) + 1
    return counts


def cmd_compare(args: argparse.Namespace) -> int:
    """Two runs of the SAME world, one observed and one governed."""
    a, b = _load(args.observe), _load(args.enforce)
    la, lb = a["ledger"], b["ledger"]
    ra, rb = _count_reactions(a), _count_reactions(b)

    def row(label: str, x, y, invert: bool = False) -> None:
        try:
            delta = y - x
            sign = "+" if delta > 0 else ""
            good = (delta < 0) if invert else (delta > 0)
            mark = "" if delta == 0 else ("  <-- " if good else "  <-- ")
            change = f"{sign}{delta:g}{mark}".rstrip()
        except TypeError:
            change = ""
        print(f"  {label:<38} {str(x):>9} {str(y):>10}   {change}")

    print("=" * 74)
    print(f"SAME WORLD, SAME SEED ({a['seed']}), SAME AGENTS — OBSERVED vs GOVERNED")
    print("=" * 74)
    print(f"  {'':<38} {'OBSERVE':>9} {'ENFORCE':>10}")

    print("\n  TRAFFIC")
    row("tool calls seen by Commons", la["calls"], lb["calls"])
    row("forwarded to the real vendors", la["forwarded"], lb["forwarded"], invert=True)
    row(
        "stopped by Commons",
        la["calls"] - la["forwarded"],
        lb["calls"] - lb["forwarded"],
    )

    print("\n  CONVERGENCE — the exposure. Identical, because it is the same world.")
    row(
        "customers worked by 2+ agents",
        la["customers_touched_by_multiple_agents"],
        lb["customers_touched_by_multiple_agents"],
    )
    row(
        "direct contradictions detected",
        la["contradictions_detected"],
        lb["contradictions_detected"],
    )
    row(
        "customers discounted by 2+ agents",
        la["customers_discounted_by_multiple_agents"],
        lb["customers_discounted_by_multiple_agents"],
    )

    print("\n  WHAT ACTUALLY REACHED THE CUSTOMER")
    row(
        "total discount delivered (%)",
        la["total_discount_delivered_pct"],
        lb["total_discount_delivered_pct"],
        invert=True,
    )
    row("customers who opted out", ra.get("opt_out", 0), rb.get("opt_out", 0), invert=True)
    row("customers who escalated", ra.get("escalate", 0), rb.get("escalate", 0), invert=True)
    row("customers irritated", ra.get("irritated", 0), rb.get("irritated", 0), invert=True)
    row("customers who engaged", ra.get("engage", 0), rb.get("engage", 0))

    print("\n  MODEL NOISE (kept out of the headline on purpose)")
    row("malformed tool calls", a["malformed_tool_calls"], b["malformed_tool_calls"], invert=True)
    row("duplicate calls dropped", a["duplicate_tool_calls"], b["duplicate_tool_calls"], invert=True)

    print("\n" + "-" * 74)
    print("  Every per-agent dashboard is green in BOTH runs. Each agent did its job")
    print("  correctly each time. The difference is that in one of them something could")
    print("  see all four at once.")
    print("-" * 74)
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

    run = sub.add_parser("run", help="run a simulated month through Commons")
    run.add_argument("--seed", type=int, default=4471)
    run.add_argument("--mode", choices=["OBSERVE", "ENFORCE"], default="OBSERVE")
    run.add_argument("--days", type=int, default=30)
    run.add_argument("--customers", type=int, default=20)
    run.add_argument("--limit", type=int, help="stop after N events (for smoke tests)")
    run.add_argument("--db", default="commons.db", help="the proxy's ledger, for the summary")
    run.add_argument("--out", help="write the full run report as JSON")
    run.set_defaults(func=cmd_run)

    compare = sub.add_parser("compare", help="A/B two runs of the same world")
    compare.add_argument("--observe", default="runs/observe-4471.json")
    compare.add_argument("--enforce", default="runs/enforce-4471.json")
    compare.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
