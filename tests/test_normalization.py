"""The production bug: handlers tested with plain dicts, then fed real StripeObjects.

Since stripe-python 15.0, StripeObject is not a dict subclass, so `.get()`
raises AttributeError on real events. These tests use `stripe.Event.construct_from`
- the same class `Webhook.construct_event` returns - instead of plain dicts.
"""

from __future__ import annotations

import pytest
import stripe

from app.normalize import to_plain
from app.processing import handle_event
from app.store import Store
from tests.stripe_fakes import checkout_session, event


def _real_event(evt: dict) -> stripe.Event:
    return stripe.Event.construct_from(evt, "sk_test_fake")


def test_stripe_object_is_not_a_dict():
    obj = _real_event(event("checkout.session.completed", checkout_session())).data.object

    assert not isinstance(obj, dict)
    assert obj["customer"] == "cus_123"  # item access still works...
    with pytest.raises(AttributeError):
        obj.get("customer")  # ...but this is what passed with dict fixtures and broke in production


def test_to_plain_returns_nested_plain_dicts():
    data = to_plain(_real_event(event("checkout.session.completed", checkout_session())))

    assert type(data) is dict
    assert type(data["data"]) is dict
    assert type(data["data"]["object"]) is dict
    assert data["data"]["object"].get("subscription") == "sub_123"


def test_handler_works_on_a_real_stripe_event(tmp_path):
    """Regression: a paid checkout must put the customer on the paid plan."""
    store = Store(str(tmp_path / "t.db"))
    real = _real_event(event("checkout.session.completed", checkout_session(payment_status="paid")))

    outcome = handle_event(store, real)

    assert outcome == "created"
    [sub] = store.subscriptions_for("cus_123")
    assert sub["status"] == "active"
