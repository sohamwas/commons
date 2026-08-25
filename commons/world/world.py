"""The world: a seeded, reproducible population and the events that befall it.

Same seed, same world, byte for byte. That determinism is doing double duty (handoff
§15.3): it makes the OBSERVE/ENFORCE comparison exact, and it makes the free hosted
replay possible, because a recorded run can be shipped as JSON and re-rendered with no
backend at all.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from commons.world.customers import (
    CART_ABANDONMENT_RATE,
    COD_SHARE,
    COD_RTO_RATE,
    DISPUTE_RATE,
    UPI_AUTOPAY_FAILURE_RATE,
    Customer,
)
from commons.world.events import Event, EventType, SimClock

FIRST_NAMES = [
    "Priya", "Arjun", "Meera", "Rohan", "Ananya", "Vikram", "Kavya", "Aditya",
    "Divya", "Karthik", "Sneha", "Rahul", "Ishaan", "Nisha", "Aarav", "Tara",
    "Dev", "Riya", "Manish", "Lakshmi",
]
LAST_INITIALS = ["S.", "K.", "R.", "M.", "N.", "P.", "V.", "D."]

DEFAULT_START = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)


@dataclass
class WorldConfig:
    seed: int = 4471
    n_customers: int = 20
    days: int = 30
    # Fraction of the population deliberately given 2+ concurrent conditions.
    # Disclosed in every run summary — see customers.py for why this is legitimate.
    overlap_rate: float = 0.6
    start: datetime = DEFAULT_START


@dataclass
class World:
    config: WorldConfig = field(default_factory=WorldConfig)
    customers: dict[str, Customer] = field(default_factory=dict)
    clock: SimClock = field(init=False)
    rng: random.Random = field(init=False)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.config.seed)
        self.clock = SimClock(self.config.start)

    # ------------------------------------------------------------------ population

    def build_population(self) -> None:
        cfg = self.config
        n_overlap = int(round(cfg.n_customers * cfg.overlap_rate))

        for i in range(cfg.n_customers):
            # Stable, readable identifiers. cust_4471 is Priya, the demo's worked example.
            cust_id = f"cust_{cfg.seed + i}"
            name = f"{FIRST_NAMES[i % len(FIRST_NAMES)]} {LAST_INITIALS[i % len(LAST_INITIALS)]}"
            phone = f"+9198000{(21 + i):05d}"
            email = f"{FIRST_NAMES[i % len(FIRST_NAMES)].lower()}{i}@example.com"

            customer = Customer(id=cust_id, name=name, phone=phone, email=email)

            if i == 0:
                # ONE customer is deliberately given all four conditions, as the demo's
                # worked example. This is population configuration, not agent design —
                # and it is disclosed in every run summary rather than hidden.
                self._give_all_conditions(customer)
            elif i < n_overlap:
                self._give_concurrent_conditions(customer)
            else:
                self._give_background_conditions(customer)

            self.customers[cust_id] = customer

    def _give_all_conditions(self, c: Customer) -> None:
        c.has_abandoned_cart = True
        c.cart_value_paise = 420_000  # Rs 4,200 — the cart from the demo script
        c.subscription_active = True
        c.mandate_will_fail = True
        c.pays_cod = True
        c.high_rto_risk = True
        c.will_dispute = True

    def _give_concurrent_conditions(self, c: Customer) -> None:
        """Deliberately sample the tail: this customer has several things going on.

        Note what this does NOT do — it does not tell any agent to act unusually. It
        gives a customer an abandoned cart AND a failing mandate, which is a thing that
        genuinely happens. Whether the agents then collide is up to the agents.
        """
        c.has_abandoned_cart = True
        c.cart_value_paise = self.rng.randrange(80_000, 900_000, 10_000)

        c.subscription_active = True
        c.mandate_will_fail = self.rng.random() < 0.85

        c.pays_cod = self.rng.random() < COD_SHARE + 0.2
        c.high_rto_risk = c.pays_cod and self.rng.random() < 0.5

        c.will_dispute = self.rng.random() < 0.35

    def _give_background_conditions(self, c: Customer) -> None:
        """Everyone else gets ordinary, published base rates."""
        c.has_abandoned_cart = self.rng.random() < CART_ABANDONMENT_RATE
        if c.has_abandoned_cart:
            c.cart_value_paise = self.rng.randrange(50_000, 600_000, 10_000)

        c.subscription_active = self.rng.random() < 0.35
        c.mandate_will_fail = c.subscription_active and self.rng.random() < UPI_AUTOPAY_FAILURE_RATE

        c.pays_cod = self.rng.random() < COD_SHARE
        c.high_rto_risk = c.pays_cod and self.rng.random() < COD_RTO_RATE

        c.will_dispute = self.rng.random() < DISPUTE_RATE

    # ------------------------------------------------------------------ events

    def schedule_events(self) -> None:
        """Lay down the timeline. Nothing here knows which agent will respond.

        Customers with several conditions get their events CLUSTERED into a few days
        rather than scattered across the month. This is not a thumb on the scale — it
        is the causal structure of the situation. The conditions share a root cause: a
        payment instrument that has stopped working produces a declined autopay mandate,
        an abandoned checkout, and later a disputed charge, all within days of each
        other. Scattering them uniformly over 30 days would be the LESS realistic model,
        and would also make a 24-hour frequency cap untestable by construction.
        """
        cfg = self.config
        horizon = timedelta(days=cfg.days)

        for c in self.customers.values():
            clustered = c.concurrent_condition_count >= 2
            # The shared root cause kicks off somewhere in the window; everything else
            # for this customer follows within a few days of it.
            anchor = self._when(horizon * 0.8, bias_early=True) if clustered else None

            def moment(offset_hours: tuple[float, float]) -> timedelta:
                if anchor is None:
                    return self._when(horizon)
                lo, hi = offset_hours
                return anchor + timedelta(minutes=int(self.rng.uniform(lo * 60, hi * 60)))

            if c.has_abandoned_cart:
                c.order_id = f"order_{c.id[5:]}"
                self.clock.schedule(
                    cfg.start + moment((0, 6)),
                    EventType.CART_ABANDONED,
                    c.id,
                    cart_value_paise=c.cart_value_paise,
                    order_id=c.order_id,
                )

            if c.subscription_active and c.mandate_will_fail:
                self.clock.schedule(
                    cfg.start + moment((0.5, 10)),
                    EventType.MANDATE_FAILED,
                    c.id,
                    reason="upi_autopay_declined",
                )

            if c.will_dispute:
                self.clock.schedule(
                    cfg.start + moment((20, 56)),
                    EventType.DISPUTE_FILED,
                    c.id,
                    amount_paise=self.rng.randrange(50_000, 500_000, 10_000),
                )

            if c.pays_cod and c.high_rto_risk:
                self.clock.schedule(
                    cfg.start + moment((30, 72)),
                    EventType.RTO_RISK_FLAGGED,
                    c.id,
                    risk_score=round(self.rng.uniform(0.6, 0.95), 2),
                    order_id=c.order_id or f"order_{c.id[5:]}",
                )

    def _when(self, horizon: timedelta, bias_early: bool = False) -> timedelta:
        """A moment in the window. Carts get abandoned early more often than late."""
        u = self.rng.random()
        if bias_early:
            u = u**1.6
        seconds = u * horizon.total_seconds()
        # Snap to the minute so event logs are stable and readable.
        return timedelta(seconds=int(seconds // 60) * 60)

    # ------------------------------------------------------------------ driving

    def generate(self) -> list[Event]:
        """Build the world and return its full timeline, in order."""
        self.build_population()
        self.schedule_events()
        return list(self.clock.drain())

    # ------------------------------------------------------------------ reporting

    def summary(self) -> dict:
        overlapping = [c for c in self.customers.values() if c.concurrent_condition_count >= 2]
        return {
            "seed": self.config.seed,
            "customers": len(self.customers),
            "days": self.config.days,
            "overlap_rate_configured": self.config.overlap_rate,
            "customers_with_2plus_conditions": len(overlapping),
            "share_with_2plus_conditions": round(
                len(overlapping) / max(len(self.customers), 1), 3
            ),
        }


def build_world(
    seed: int = 4471, n_customers: int = 20, days: int = 30, overlap_rate: float = 0.6
) -> World:
    return World(
        WorldConfig(seed=seed, n_customers=n_customers, days=days, overlap_rate=overlap_rate)
    )
