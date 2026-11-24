"""Turn Stripe SDK objects into plain dicts before any business logic reads them.

Since stripe-python 15.0, ``StripeObject`` is no longer a ``dict`` subclass.
On a real ``stripe.Event`` (what ``Webhook.construct_event`` returns):

* ``obj["status"]`` and ``obj.status`` still work,
* ``obj.get("status")``, ``obj.keys()`` and ``dict(obj)`` raise
  (``AttributeError`` / ``TypeError``),
* ``isinstance(obj, dict)`` is ``False``.

Handlers written and tested against plain-dict fixtures therefore pass their
tests and then crash on the first real event. Converting once, at the edge,
with ``to_dict()`` (recursive by default) means everything downstream only
ever sees plain ``dict`` / ``list`` values - the same shape the tests use.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from stripe import StripeObject


def to_plain(obj: StripeObject | Mapping[str, Any]) -> dict[str, Any]:
    """Return a plain, recursively converted ``dict`` for a Stripe object or mapping."""
    if isinstance(obj, StripeObject):
        return obj.to_dict()
    if isinstance(obj, Mapping):
        return dict(obj)
    raise TypeError(f"expected a StripeObject or mapping, got {type(obj).__name__}")
