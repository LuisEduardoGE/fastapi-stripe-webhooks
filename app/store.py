"""SQLite persistence: an event inbox (idempotency) and the subscription read model."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from app.subscriptions import Change

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id           TEXT PRIMARY KEY,          -- Stripe event.id: the idempotency key
    type         TEXT NOT NULL,
    created      INTEGER NOT NULL,          -- Stripe event.created (unix seconds)
    payload      TEXT NOT NULL,             -- normalized event JSON
    status       TEXT NOT NULL,             -- pending | processed | failed
    outcome      TEXT,                      -- created | applied | stale | terminal | no-op | ignored | unhandled
    error        TEXT,
    received_at  TEXT NOT NULL,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id                   TEXT PRIMARY KEY,
    customer_id          TEXT NOT NULL,
    status               TEXT NOT NULL,
    price_id             TEXT,
    cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
    last_event_id        TEXT NOT NULL,
    last_event_created   INTEGER NOT NULL,  -- ordering guard for out-of-order delivery
    updated_at           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS subscriptions_customer ON subscriptions (customer_id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # Autocommit mode + explicit BEGIN IMMEDIATE where a read-then-write must
        # be atomic; a connection per call keeps it safe across threads.
        conn = sqlite3.connect(self.path, isolation_level=None, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # -- event inbox -------------------------------------------------------

    def record_event(self, event: dict[str, Any]) -> bool:
        """Persist a verified event. Returns False if this event.id was already seen."""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO events (id, type, created, payload, status, received_at)"
                " VALUES (?, ?, ?, ?, 'pending', ?)",
                (event["id"], event["type"], event["created"], json.dumps(event), _now()),
            )
            return cur.rowcount == 1

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        return dict(row) if row else None

    def unfinished_event_ids(self) -> list[str]:
        """Events that were acked but not (successfully) processed, oldest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM events WHERE status != 'processed' ORDER BY created, received_at"
            ).fetchall()
        return [r["id"] for r in rows]

    def mark_event(self, event_id: str, status: str, outcome: str | None, error: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE events SET status = ?, outcome = ?, error = ?, processed_at = ? WHERE id = ?",
                (status, outcome, error, _now(), event_id),
            )

    # -- subscription state machine ----------------------------------------

    def apply_change(self, change: Change, event_id: str, event_created: int) -> str:
        """Apply ``change`` unless the event is older than the stored state.

        Returns one of: created, applied, stale, terminal, no-op.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")  # serialize the read-check-write below
            try:
                outcome = self._apply_locked(conn, change, event_id, event_created)
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return outcome

    @staticmethod
    def _apply_locked(conn: sqlite3.Connection, change: Change, event_id: str, event_created: int) -> str:
        row = conn.execute(
            "SELECT status, last_event_created FROM subscriptions WHERE id = ?",
            (change.subscription_id,),
        ).fetchone()

        if row is None:
            conn.execute(
                "INSERT INTO subscriptions (id, customer_id, status, price_id, cancel_at_period_end,"
                " last_event_id, last_event_created, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    change.subscription_id,
                    change.customer_id,
                    change.status or change.initial_status,
                    change.price_id,
                    int(bool(change.cancel_at_period_end)),
                    event_id,
                    event_created,
                    _now(),
                ),
            )
            return "created"

        # Stripe does not guarantee delivery order. `created` has 1-second
        # resolution, so events from the same second are applied in arrival order.
        if event_created < row["last_event_created"]:
            return "stale"
        # A canceled subscription never comes back; a resubscribe is a new id.
        if row["status"] == "canceled" and change.status != "canceled":
            return "terminal"
        if change.from_statuses is not None and row["status"] not in change.from_statuses:
            return "no-op"

        conn.execute(
            "UPDATE subscriptions SET"
            " customer_id = COALESCE(?, customer_id),"
            " status = COALESCE(?, status),"
            " price_id = COALESCE(?, price_id),"
            " cancel_at_period_end = COALESCE(?, cancel_at_period_end),"
            " last_event_id = ?, last_event_created = ?, updated_at = ?"
            " WHERE id = ?",
            (
                change.customer_id,
                change.status,
                change.price_id,
                None if change.cancel_at_period_end is None else int(change.cancel_at_period_end),
                event_id,
                event_created,
                _now(),
                change.subscription_id,
            ),
        )
        return "applied"

    def subscriptions_for(self, customer_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, status, price_id, cancel_at_period_end, last_event_id, last_event_created"
                " FROM subscriptions WHERE customer_id = ? ORDER BY last_event_created DESC",
                (customer_id,),
            ).fetchall()
        return [{**dict(r), "cancel_at_period_end": bool(r["cancel_at_period_end"])} for r in rows]
