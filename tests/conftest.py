from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.stripe_fakes import body, sign

# Obviously fake; generated for the tests, never a real endpoint secret.
SECRET = "whsec_test_fake"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(webhook_secret=SECRET, database_path=str(tmp_path / "test.db"))


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def post_event(client: TestClient) -> Callable[..., Any]:
    """POST a correctly signed event (BackgroundTasks run before this returns)."""

    def _post(evt: dict[str, Any]) -> Any:
        payload = body(evt)
        return client.post(
            "/webhooks/stripe",
            content=payload,
            headers={"Stripe-Signature": sign(payload, SECRET), "Content-Type": "application/json"},
        )

    return _post
