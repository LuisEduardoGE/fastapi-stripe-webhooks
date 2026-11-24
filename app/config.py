"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # One secret per endpoint: the Dashboard endpoint, `stripe listen` and each
    # environment all have their own `whsec_...` value.
    webhook_secret: str = ""
    database_path: str = "webhooks.db"
    # Reject signed timestamps older than this (seconds). Stripe's default is 300.
    tolerance_seconds: int = 300

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            webhook_secret=os.getenv("STRIPE_WEBHOOK_SECRET", ""),
            database_path=os.getenv("DATABASE_PATH", "webhooks.db"),
            tolerance_seconds=int(os.getenv("STRIPE_WEBHOOK_TOLERANCE", "300")),
        )
