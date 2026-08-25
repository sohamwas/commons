"""Simulated time and the events that flow through it.

The clock is a priority queue ordered by (when, sequence). The sequence number is what
makes the simulation reproducible: two events at the same instant must always come out
in the same order, and insertion order alone is not stable enough to rely on.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum


class EventType(StrEnum):
    CART_ABANDONED = "cart_abandoned"
    MANDATE_FAILED = "mandate_failed"
    DISPUTE_FILED = "dispute_filed"
    DISPUTE_RESOLVED = "dispute_resolved"
    RTO_RISK_FLAGGED = "rto_risk_flagged"
    ORDER_PLACED = "order_placed"

    @property
    def agent(self) -> str | None:
        """Which agent this event wakes up.

        Straight from Razorpay's published job descriptions — an abandoned cart is Cart
        Recovery's job, a failed mandate is Subscription Recovery's. Nothing here is
        arranged to make agents meet; they are simply doing what they were built to do.
        """
        return {
            EventType.CART_ABANDONED: "cart-recovery",
            EventType.MANDATE_FAILED: "subscription-recovery",
            EventType.DISPUTE_FILED: "dispute-responder",
            EventType.RTO_RISK_FLAGGED: "rto-shield",
        }.get(self)


@dataclass(order=True)
class Event:
    at: datetime
    seq: int
    type: EventType = field(compare=False)
    customer_id: str = field(compare=False)
    payload: dict = field(default_factory=dict, compare=False)

    def describe(self) -> str:
        bits = " ".join(f"{k}={v}" for k, v in sorted(self.payload.items()))
        return f"{self.at:%Y-%m-%d %H:%M}  {self.type:<18} {self.customer_id:<12} {bits}"


class SimClock:
    """A deterministic event queue over simulated time.

    Runs a 30-day month in about a minute of wall time. Rules never see wall time —
    they read `sim_ts` from the ledger — so a frequency cap of "once per 24 hours"
    means 24 simulated hours regardless of how fast the run actually executes.
    """

    def __init__(self, start: datetime) -> None:
        self.start = start
        self.now = start
        self._queue: list[Event] = []
        self._seq = 0

    def schedule(
        self, at: datetime, event_type: EventType, customer_id: str, **payload
    ) -> Event:
        event = Event(at=at, seq=self._seq, type=event_type, customer_id=customer_id, payload=payload)
        self._seq += 1
        heapq.heappush(self._queue, event)
        return event

    def schedule_in(
        self, delta: timedelta, event_type: EventType, customer_id: str, **payload
    ) -> Event:
        return self.schedule(self.now + delta, event_type, customer_id, **payload)

    def pop(self) -> Event | None:
        if not self._queue:
            return None
        event = heapq.heappop(self._queue)
        # Time only moves forward, even if something is scheduled in the past.
        self.now = max(self.now, event.at)
        return event

    def drain(self, until: datetime | None = None):
        while self._queue:
            if until is not None and self._queue[0].at > until:
                return
            event = self.pop()
            if event is None:
                return
            yield event

    def __len__(self) -> int:
        return len(self._queue)
