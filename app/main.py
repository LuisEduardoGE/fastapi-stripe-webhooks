"""FastAPI app: a Stripe webhook endpoint that verifies, dedupes, acks fast, then processes."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import stripe
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

from app.config import Settings
from app.normalize import to_plain
from app.processing import process_event, process_unfinished
from app.store import Store
from app.subscriptions import plan_for

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """App factory (run with `uvicorn app.main:create_app --factory`)."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = settings or Settings.from_env()
    store = Store(settings.database_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        redriven = process_unfinished(store)
        if redriven:
            log.info("re-processed %d unfinished events on startup", redriven)
        yield

    app = FastAPI(title="FastAPI Stripe webhooks", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhooks/stripe")
    async def stripe_webhook(
        request: Request,
        background: BackgroundTasks,
        stripe_signature: str | None = Header(default=None),
    ) -> dict[str, Any]:
        if not settings.webhook_secret:
            # 5xx on purpose: Stripe keeps retrying until the config is fixed.
            raise HTTPException(status_code=500, detail="webhook secret not configured")

        # The signature covers the exact bytes Stripe sent. Read the raw body:
        # never `await request.json()` or a Pydantic body model, and never
        # re-serialize - any whitespace or key-order change breaks the HMAC.
        payload = await request.body()
        try:
            event = stripe.Webhook.construct_event(
                payload, stripe_signature, settings.webhook_secret, tolerance=settings.tolerance_seconds
            )
        except stripe.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="invalid signature") from None
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid payload") from None

        # Normalize once, at the edge: everything below sees plain dicts.
        data = to_plain(event)

        # Idempotency: event.id is the key. A duplicate delivery is acked with
        # 200 so Stripe stops retrying, and is not processed again.
        if not store.record_event(data):
            return {"received": True, "duplicate": True}

        # Fast ack: the event is durably stored, so return 2xx now and do the
        # real work after the response (a queue worker in production).
        background.add_task(process_event, store, data["id"])
        return {"received": True, "duplicate": False}

    @app.get("/subscriptions/{customer_id}")
    def get_subscriptions(customer_id: str) -> dict[str, Any]:
        subs = store.subscriptions_for(customer_id)
        return {
            "customer_id": customer_id,
            "plan": plan_for([s["status"] for s in subs]),
            "subscriptions": subs,
        }

    return app
