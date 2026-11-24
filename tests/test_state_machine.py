"""Subscription state machine: ordering, transitions and the read model."""

from __future__ import annotations

from tests.stripe_fakes import T0, checkout_session, event, invoice, subscription


def _read(client, customer: str = "cus_123") -> dict:
    return client.get(f"/subscriptions/{customer}").json()


def _outcome(client, evt: dict) -> str:
    return client.app.state.store.get_event(evt["id"])["outcome"]


def test_checkout_completed_puts_customer_on_paid_plan(client, post_event):
    post_event(event("checkout.session.completed", checkout_session(payment_status="paid")))

    read = _read(client)
    assert read["plan"] == "pro"
    assert read["subscriptions"][0]["id"] == "sub_123"
    assert read["subscriptions"][0]["status"] == "active"


def test_checkout_with_pending_async_payment_is_not_entitled_yet(client, post_event):
    post_event(event("checkout.session.completed", checkout_session(payment_status="unpaid"), created=T0))
    assert _read(client)["plan"] == "free"

    post_event(event("invoice.paid", invoice(), created=T0 + 60))  # e.g. a bank debit settles
    assert _read(client)["plan"] == "pro"


def test_one_off_payment_checkout_is_ignored(client, post_event):
    evt = event("checkout.session.completed", checkout_session(mode="payment"))
    post_event(evt)

    assert _outcome(client, evt) == "ignored"
    assert _read(client)["subscriptions"] == []


def test_subscription_created_stores_status_and_price(client, post_event):
    post_event(event("customer.subscription.created", subscription("trialing", price="price_pro_yearly")))

    sub = _read(client)["subscriptions"][0]
    assert (sub["status"], sub["price_id"]) == ("trialing", "price_pro_yearly")


def test_out_of_order_update_is_ignored(client, post_event):
    newer = event("customer.subscription.updated", subscription("active"), created=T0 + 100)
    older = event("customer.subscription.updated", subscription("past_due"), created=T0 + 50)

    post_event(newer)
    post_event(older)  # delivered late, e.g. a retry of an earlier failed delivery

    assert _outcome(client, older) == "stale"
    assert _read(client)["subscriptions"][0]["status"] == "active"


def test_payment_failed_moves_active_subscription_to_past_due(client, post_event):
    post_event(event("customer.subscription.created", subscription("active"), created=T0))
    post_event(event("invoice.payment_failed", invoice(), created=T0 + 10))

    read = _read(client)
    assert read["subscriptions"][0]["status"] == "past_due"
    assert read["plan"] == "free"


def test_invoice_paid_recovers_past_due_new_api_shape(client, post_event):
    """API 2025-03-31+ moved the subscription id to invoice.parent.subscription_details."""
    post_event(event("customer.subscription.created", subscription("past_due"), created=T0))
    post_event(event("invoice.paid", invoice(new_api_shape=True), created=T0 + 10))

    assert _read(client)["subscriptions"][0]["status"] == "active"


def test_invoice_paid_does_not_override_trialing(client, post_event):
    post_event(event("customer.subscription.created", subscription("trialing"), created=T0))
    paid = event("invoice.paid", invoice(), created=T0 + 1)  # the $0 trial invoice
    post_event(paid)

    assert _outcome(client, paid) == "no-op"
    assert _read(client)["subscriptions"][0]["status"] == "trialing"


def test_deleted_cancels_and_is_terminal(client, post_event):
    post_event(event("customer.subscription.created", subscription("active"), created=T0))
    post_event(event("customer.subscription.deleted", subscription("canceled"), created=T0 + 10))
    late_paid = event("invoice.paid", invoice(), created=T0 + 20)
    post_event(late_paid)

    read = _read(client)
    assert read["subscriptions"][0]["status"] == "canceled"
    assert read["plan"] == "free"
    assert _outcome(client, late_paid) == "terminal"


def test_unknown_customer_is_on_free_plan(client):
    assert _read(client, "cus_nobody") == {"customer_id": "cus_nobody", "plan": "free", "subscriptions": []}
