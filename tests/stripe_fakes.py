"""Build Stripe-shaped events and sign them locally - no network, no real keys."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from uuid import uuid4

T0 = 1_760_000_000  # arbitrary event.created base (unix seconds)


def sign(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    """Stripe-Signature header: HMAC-SHA256 of "{t}.{payload}" keyed with the endpoint secret."""
    t = int(time.time()) if timestamp is None else timestamp
    signed = f"{t}.".encode() + payload
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={t},v1={v1}"


def event(event_type: str, obj: dict[str, Any], *, created: int = T0, event_id: str | None = None) -> dict[str, Any]:
    return {
        "id": event_id or f"evt_{uuid4().hex[:24]}",
        "object": "event",
        "api_version": "2025-03-31.basil",
        "created": created,
        "livemode": False,
        "pending_webhooks": 1,
        "type": event_type,
        "data": {"object": obj},
    }


def subscription(
    status: str = "active",
    *,
    sub_id: str = "sub_123",
    customer: str = "cus_123",
    price: str = "price_pro_monthly",
    cancel_at_period_end: bool = False,
) -> dict[str, Any]:
    return {
        "id": sub_id,
        "object": "subscription",
        "customer": customer,
        "status": status,
        "cancel_at_period_end": cancel_at_period_end,
        "items": {
            "object": "list",
            "data": [{"id": "si_1", "object": "subscription_item", "price": {"id": price, "object": "price"}}],
        },
    }


def checkout_session(
    *, sub_id: str = "sub_123", customer: str = "cus_123", payment_status: str = "paid", mode: str = "subscription"
) -> dict[str, Any]:
    return {
        "id": "cs_test_1",
        "object": "checkout.session",
        "mode": mode,
        "customer": customer,
        "subscription": sub_id if mode == "subscription" else None,
        "payment_status": payment_status,
        "client_reference_id": "user_42",
    }


def invoice(*, sub_id: str = "sub_123", customer: str = "cus_123", new_api_shape: bool = False) -> dict[str, Any]:
    inv: dict[str, Any] = {"id": "in_1", "object": "invoice", "customer": customer}
    if new_api_shape:  # API 2025-03-31+: subscription moved under `parent`
        inv["parent"] = {"type": "subscription_details", "subscription_details": {"subscription": sub_id}}
    else:
        inv["subscription"] = sub_id
    return inv


def body(evt: dict[str, Any]) -> bytes:
    """Serialize like Stripe does: pretty-printed JSON. Any other byte layout changes the HMAC."""
    return json.dumps(evt, indent=2).encode()
