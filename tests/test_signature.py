"""Signature verification happens on the raw request body, before anything else."""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import SECRET
from tests.stripe_fakes import body, event, sign, subscription


def _post(client: TestClient, payload: bytes, signature: str | None):
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["Stripe-Signature"] = signature
    return client.post("/webhooks/stripe", content=payload, headers=headers)


def test_valid_signature_is_accepted_and_processed(client):
    evt = event("customer.subscription.created", subscription("active"))
    payload = body(evt)

    resp = _post(client, payload, sign(payload, SECRET))

    assert resp.status_code == 200
    assert resp.json() == {"received": True, "duplicate": False}
    stored = client.app.state.store.get_event(evt["id"])
    assert stored["status"] == "processed"
    assert stored["outcome"] == "created"


def test_missing_signature_header_is_rejected(client):
    resp = _post(client, body(event("invoice.paid", {})), None)
    assert resp.status_code == 400


def test_signature_with_wrong_secret_is_rejected(client):
    payload = body(event("invoice.paid", {}))
    resp = _post(client, payload, sign(payload, "whsec_some_other_endpoint"))
    assert resp.status_code == 400


def test_tampered_body_is_rejected(client):
    payload = body(event("customer.subscription.updated", subscription("canceled")))
    signature = sign(payload, SECRET)
    tampered = payload.replace(b'"canceled"', b'"active"')

    resp = _post(client, tampered, signature)

    assert resp.status_code == 400


def test_reserialized_json_fails_even_though_content_is_identical(client):
    """Why the endpoint reads `request.body()`: parse + dump changes the bytes, so the HMAC fails."""
    payload = body(event("customer.subscription.created", subscription("active")))
    signature = sign(payload, SECRET)
    reserialized = json.dumps(json.loads(payload)).encode()  # same data, compact separators
    assert json.loads(reserialized) == json.loads(payload)

    resp = _post(client, reserialized, signature)

    assert resp.status_code == 400


def test_stale_timestamp_is_rejected_as_replay(client):
    payload = body(event("customer.subscription.created", subscription("active")))
    ten_minutes_ago = int(time.time()) - 600  # tolerance is 300s

    resp = _post(client, payload, sign(payload, SECRET, timestamp=ten_minutes_ago))

    assert resp.status_code == 400


def test_rejected_requests_are_not_stored(client):
    evt = event("customer.subscription.created", subscription("active"))
    _post(client, body(evt), sign(body(evt), "whsec_wrong"))
    assert client.app.state.store.get_event(evt["id"]) is None


def test_missing_secret_returns_5xx_so_stripe_retries(tmp_path):
    settings = Settings(webhook_secret="", database_path=str(tmp_path / "t.db"))
    with TestClient(create_app(settings)) as client:
        payload = body(event("invoice.paid", {}))
        resp = _post(client, payload, sign(payload, SECRET))
    assert resp.status_code == 500
