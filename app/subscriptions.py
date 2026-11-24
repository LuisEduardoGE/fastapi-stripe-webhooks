"""Subscription state machine: map a (plain-dict) Stripe event to a state change.

This module is pure - no I/O. ``Store.apply_change`` enforces ordering
(``event.created``) and the terminal ``canceled`` state when it persists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Statuses that grant the paid plan. Keeping access while `past_due` (a grace
# period during dunning) is a business decision; this demo does not.
ENTITLED_STATUSES = frozenset({"active", "trialing"})

HANDLED_EVENT_TYPES = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.paid",
        "invoice.payment_failed",
    }
)


@dataclass(frozen=True)
class Change:
    """A desired update to one subscription row. ``None`` fields are left unchanged."""

    subscription_id: str
    customer_id: str
    status: str | None = None
    price_id: str | None = None
    cancel_at_period_end: bool | None = None
    # Status assumed when the row does not exist yet.
    initial_status: str = "incomplete"
    # Only apply when the current status is in this set (None = from any status).
    from_statuses: frozenset[str] | None = None


def _id(value: Any) -> str | None:
    """Stripe fields like `customer` are an id string, or an object when expanded."""
    if isinstance(value, dict):
        return value.get("id")
    return value


def _price_id(subscription: dict[str, Any]) -> str | None:
    items = (subscription.get("items") or {}).get("data") or []
    if not items:
        return None
    return _id(items[0].get("price"))


def _invoice_subscription_id(invoice: dict[str, Any]) -> str | None:
    # API versions before 2025-03-31 put it at `invoice.subscription`; newer ones
    # moved it to `invoice.parent.subscription_details.subscription`.
    if invoice.get("subscription"):
        return _id(invoice["subscription"])
    details = (invoice.get("parent") or {}).get("subscription_details") or {}
    return _id(details.get("subscription"))


def derive_change(event: dict[str, Any]) -> Change | None:
    """Return the state change an event implies, or None if it carries none.

    ``event`` must be a plain dict (see ``app.normalize.to_plain``).
    """
    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        subscription_id = _id(obj.get("subscription"))
        if obj.get("mode") != "subscription" or not subscription_id:
            return None  # one-off payment, nothing to track here
        paid = obj.get("payment_status") in {"paid", "no_payment_required"}
        # Async payment methods complete checkout before money moves: link the
        # customer now and let invoice / subscription events set the status.
        return Change(
            subscription_id=subscription_id,
            customer_id=_id(obj.get("customer")),
            status="active" if paid else None,
        )

    if event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        # The payload is a full snapshot of the subscription: authoritative.
        return Change(
            subscription_id=obj["id"],
            customer_id=_id(obj["customer"]),
            status=obj["status"],
            price_id=_price_id(obj),
            cancel_at_period_end=bool(obj.get("cancel_at_period_end")),
        )

    if event_type == "customer.subscription.deleted":
        return Change(
            subscription_id=obj["id"],
            customer_id=_id(obj["customer"]),
            status="canceled",
            price_id=_price_id(obj),
            initial_status="canceled",
        )

    if event_type in {"invoice.paid", "invoice.payment_failed"}:
        subscription_id = _invoice_subscription_id(obj)
        if not subscription_id:
            return None  # invoice not tied to a subscription
        if event_type == "invoice.paid":
            # Recovers a failed / pending subscription; never overrides `trialing`.
            return Change(
                subscription_id=subscription_id,
                customer_id=_id(obj.get("customer")),
                status="active",
                initial_status="active",
                from_statuses=frozenset({"incomplete", "past_due", "unpaid"}),
            )
        return Change(
            subscription_id=subscription_id,
            customer_id=_id(obj.get("customer")),
            status="past_due",
            initial_status="past_due",
            from_statuses=frozenset({"active", "trialing"}),
        )

    return None


def plan_for(statuses: list[str]) -> str:
    """The read-model answer to "what plan is this customer on?"."""
    return "pro" if any(s in ENTITLED_STATUSES for s in statuses) else "free"
