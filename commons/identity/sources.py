"""Where a merchant's customer list actually comes from.

Nobody types their customers into a text box. The realistic sources, in the order a
merchant would reach for them:

  1. RAZORPAY ITSELF. Their customers are already there — Commons is holding the same
     API keys their agents use, so this needs no new credential, no export, and no
     mapping. `GET /v1/customers` returns id, name, email and contact, which is exactly
     the handle set identity resolution needs. This is the default.
  2. Payments and orders. Customers created implicitly at checkout never appear in the
     Customers API, so a merchant with a guest-checkout storefront would sync almost
     nobody from (1). Contacts are pulled from recent payments instead.
  3. A CSV export. Every CRM, storefront and spreadsheet can produce one, and it is the
     only universal option for a merchant whose customer master lives elsewhere.
  4. A direct database connection. Deliberately NOT implemented: it would mean handing a
     gateway read access to the merchant's production database for data they can already
     export, which is a much larger ask than the problem justifies.

Every path ends in the same place — a declared mapping from vendor handles to one
canonical person — because Commons never infers that a phone and an email are the same
human (see identity/resolver.py).
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass, field

import httpx2 as httpx

logger = logging.getLogger(__name__)

RAZORPAY_API = "https://api.razorpay.com/v1"


@dataclass
class SyncResult:
    source: str
    found: int = 0
    customers: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_entities(self) -> list[dict]:
        return [
            {
                "ref": c.get("customer_id") or c.get("phone") or c.get("email"),
                "display_name": c.get("name")
                or c.get("customer_id")
                or c.get("phone")
                or c.get("email"),
                "handles": {
                    k: v
                    for k, v in c.items()
                    if k in ("customer_id", "phone", "email") and v
                },
            }
            for c in self.customers
            if any(c.get(k) for k in ("customer_id", "phone", "email"))
        ]


def _auth_header() -> dict[str, str]:
    key_id = os.environ.get("RAZORPAY_KEY_ID", "").strip()
    secret = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id or not secret:
        raise RuntimeError("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not configured")
    token = base64.b64encode(f"{key_id}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def sync_from_razorpay(limit: int = 100, include_payments: bool = True) -> SyncResult:
    """Pull the merchant's customers straight out of Razorpay.

    Uses the credentials Commons already holds, so there is nothing extra to configure.
    """
    result = SyncResult(source="razorpay")
    headers = _auth_header()
    seen: dict[str, dict] = {}

    with httpx.Client(headers=headers, timeout=45.0) as client:
        # ---- registered customers ----
        try:
            res = client.get(f"{RAZORPAY_API}/customers", params={"count": min(limit, 100)})
            res.raise_for_status()
            for item in res.json().get("items", []):
                record = {
                    "customer_id": item.get("id"),
                    "name": item.get("name"),
                    "email": item.get("email"),
                    "phone": item.get("contact"),
                }
                seen[record["customer_id"]] = record
        except Exception as exc:  # noqa: BLE001 — report, do not crash the sync
            result.warnings.append(f"customers API: {str(exc)[:160]}")

        # ---- contacts seen on payments ----
        #
        # A storefront using guest checkout creates almost no Customer records, so the
        # call above can legitimately return nothing while the merchant has thousands of
        # buyers. Their contact details are on the payments.
        if include_payments:
            try:
                res = client.get(f"{RAZORPAY_API}/payments", params={"count": min(limit, 100)})
                res.raise_for_status()
                for item in res.json().get("items", []):
                    contact, email = item.get("contact"), item.get("email")
                    if not contact and not email:
                        continue
                    key = item.get("customer_id") or contact or email
                    existing = seen.get(key, {})
                    seen[key] = {
                        "customer_id": item.get("customer_id") or existing.get("customer_id"),
                        "name": existing.get("name"),
                        "email": email or existing.get("email"),
                        "phone": contact or existing.get("phone"),
                    }
            except Exception as exc:  # noqa: BLE001
                result.warnings.append(f"payments API: {str(exc)[:160]}")

    result.customers = [
        {k: v for k, v in record.items() if v} for record in seen.values()
    ]
    result.found = len(result.customers)

    if result.found == 0 and not result.warnings:
        result.warnings.append(
            "No customers found. On a test account this is normal until some payments "
            "exist; on a live account it usually means checkout is guest-only, so import "
            "a CSV from wherever your customer master lives."
        )

    single_handle = sum(
        1
        for c in result.customers
        if len([k for k in ("customer_id", "phone", "email") if c.get(k)]) < 2
    )
    if single_handle:
        result.warnings.append(
            f"{single_handle} of {result.found} customers arrived with only one handle. "
            "Commons cannot recognise them if an agent contacts them on another channel."
        )

    logger.info("razorpay sync: %d customers, %d warnings", result.found, len(result.warnings))
    return result
