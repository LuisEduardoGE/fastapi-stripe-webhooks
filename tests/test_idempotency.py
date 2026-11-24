"""event.id is the idempotency key; acked events are processed exactly once."""

from __future__ import annotations

from app import processing
from app.processing import process_unfinished
from tests.stripe_fakes import event, subscription


def test_duplicate_delivery_is_acked_but_not_reprocessed(client, post_event, monkeypatch):
    calls = []
    real_handle = processing.handle_event

    def counting_handle(store, evt):
        calls.append(evt["id"])
        return real_handle(store, evt)

    monkeypatch.setattr(processing, "handle_event", counting_handle)
    evt = event("customer.subscription.created", subscription("active"))

    first = post_event(evt)
    second = post_event(evt)  # Stripe retry / redelivery of the same event

    assert first.status_code == second.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert calls == [evt["id"]]


def test_unhandled_event_type_is_acked_and_recorded(client, post_event):
    evt = event("customer.created", {"id": "cus_123", "object": "customer"})

    resp = post_event(evt)

    assert resp.status_code == 200
    stored = client.app.state.store.get_event(evt["id"])
    assert (stored["status"], stored["outcome"]) == ("processed", "unhandled")


def test_processing_failure_is_kept_and_redriven(client, post_event, monkeypatch):
    """A bug after the 2xx ack must not lose the event: it stays `failed` in the inbox."""
    real_handle = processing.handle_event

    def boom(store, evt):
        raise RuntimeError("bug in handler")

    monkeypatch.setattr(processing, "handle_event", boom)
    evt = event("customer.subscription.created", subscription("active"))

    assert post_event(evt).status_code == 200  # Stripe sees success either way
    store = client.app.state.store
    assert store.get_event(evt["id"])["status"] == "failed"

    monkeypatch.setattr(processing, "handle_event", real_handle)  # "deploy the fix"
    assert process_unfinished(store) == 1
    assert store.get_event(evt["id"])["status"] == "processed"
    assert client.get("/subscriptions/cus_123").json()["plan"] == "pro"
