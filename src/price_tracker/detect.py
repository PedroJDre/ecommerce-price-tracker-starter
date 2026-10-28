"""Decide what changed between the last check and this one."""

import sqlite3
from decimal import Decimal

from price_tracker.models import Event, Offer, Watch


def changes(watch: Watch, offer: Offer, previous: sqlite3.Row | None, *, watch_is_new: bool,
            threshold_percent: float) -> list[Event]:  # fmt: skip
    def event(type_: str, old: Decimal | None = None) -> Event:
        return Event(watch.name, type_, offer.title, offer.url, old, offer.price, offer.currency)

    events: list[Event] = []
    new = offer.price
    old = Decimal(previous["price"]) if previous is not None and previous["price"] else None

    if previous is None:
        # A listing we have never seen, in a search we already track: worth knowing.
        if watch.kind == "search" and not watch_is_new:
            events.append(event("new_listing"))
        if watch.target_price is not None and new is not None and new <= watch.target_price and offer.available:
            events.append(event("below_target"))
        return events

    was_available = bool(previous["available"])
    if not was_available and offer.available:
        events.append(event("back_in_stock", old))
    elif was_available and not offer.available:
        events.append(event("out_of_stock", old))

    if old is not None and new is not None and old > 0 and new != old:
        change = float((new - old) / old * 100)
        if change <= -threshold_percent:
            events.append(event("price_drop", old))
        elif change >= threshold_percent:
            events.append(event("price_up", old))

    # Only when the price crosses the target, so you don't get the same alert every run.
    if watch.target_price is not None and new is not None and offer.available and new <= watch.target_price:
        if old is None or old > watch.target_price or not was_available:
            events.append(event("below_target", old))
    return events
