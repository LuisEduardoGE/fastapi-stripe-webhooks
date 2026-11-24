"""Process events from the inbox. Runs after the HTTP response has been sent."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.normalize import to_plain
from app.store import Store
from app.subscriptions import HANDLED_EVENT_TYPES, derive_change

log = logging.getLogger(__name__)


def handle_event(store: Store, event: Any) -> str:
    """Apply one event to the subscription read model and return the outcome.

    Accepts a ``stripe.Event`` or a plain dict: it is normalized first, so the
    state machine never calls dict methods on a ``StripeObject``.
    """
    data = to_plain(event)
    if data["type"] not in HANDLED_EVENT_TYPES:
        return "unhandled"
    change = derive_change(data)
    if change is None:
        return "ignored"
    return store.apply_change(change, data["id"], data["created"])


def process_event(store: Store, event_id: str) -> None:
    """Process a recorded event and record the result. Never raises.

    In production this is the body of a queue worker (Celery, RQ, SQS, ...);
    here it is a FastAPI BackgroundTask. Failures stay in the inbox as
    ``failed`` and are retried by ``process_unfinished`` - Stripe will not
    retry them, because the delivery was already acknowledged with a 2xx.
    """
    row = store.get_event(event_id)
    if row is None or row["status"] == "processed":
        return
    try:
        outcome = handle_event(store, json.loads(row["payload"]))
    except Exception as exc:
        log.exception("processing %s failed", event_id)
        store.mark_event(event_id, "failed", None, error=f"{type(exc).__name__}: {exc}")
        return
    store.mark_event(event_id, "processed", outcome)
    log.info("event %s (%s): %s", event_id, row["type"], outcome)


def process_unfinished(store: Store) -> int:
    """Re-drive events that were acked but never processed (crash, deploy, bug)."""
    ids = store.unfinished_event_ids()
    for event_id in ids:
        process_event(store, event_id)
    return len(ids)
