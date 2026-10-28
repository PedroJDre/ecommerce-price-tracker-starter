"""Build a dashboard from 30 days of made-up prices, to see what it looks like before your own data grows.

    uv run python scripts/demo.py   ->  demo/index.html

Everything here is sample data. Nothing is fetched from the internet.
"""

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from price_tracker import report
from price_tracker.config import Settings
from price_tracker.db import Database
from price_tracker.detect import changes
from price_tracker.models import Offer, Watch

OUT = Path("demo")
random.seed(7)

PRODUCTS = [
    (Watch("Noise-cancelling headphones", "product", "page", url="https://example.com/headphones",
           target_price=Decimal("279")), "Studio ANC Headphones, Black", 349, "USD"),
    (Watch("Espresso machine", "product", "shopify", url="https://example.com/products/espresso"),
     "Barista Pro Espresso Machine", 699, "USD"),
    (Watch("Running shoes", "product", "page", url="https://example.com/shoes"), "Trail Runner 4, size 42",
     189900, "ARS"),
]  # fmt: skip
SEARCH = Watch("Used compact SUVs", "search", "mercadolibre", query="compact suv 2023")
MODELS = ["Urban 1.5T", "Cross Plus", "Sport AT", "Comfort MT", "Elite CVT", "Active 4x2", "Max AWD", "City Pro"]


def walk(start: float, days: int, drift: float, jump_day: int | None = None, jump: float = 0) -> list[Decimal]:
    prices, price = [], start
    for day in range(days):
        price *= 1 + random.uniform(-0.012, 0.012) + drift
        if day == jump_day:
            price *= 1 + jump
        prices.append(Decimal(round(price)))
    return prices


def main() -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / "demo.db").unlink(missing_ok=True)
    db = Database(OUT / "demo.db")
    settings = Settings(database=OUT / "demo.db", report=OUT / "index.html", title="Price tracker · demo data")
    days = 30
    start = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)

    series = [walk(p[2], days, -0.002, jump_day=22, jump=-0.14) for p in PRODUCTS[:1]]
    series += [walk(PRODUCTS[1][2], days, 0.001, jump_day=12, jump=0.08), walk(PRODUCTS[2][2], days, 0.004)]
    listings = {f"MLA{i}": (f"Compact SUV {random.choice(MODELS)} 2023, {random.randint(8, 40)}.000 km",
                            random.randint(23000, 36000), random.randint(0, 20)) for i in range(40)}  # fmt: skip

    for day in range(days):
        at = (start + timedelta(days=day)).isoformat(timespec="seconds")
        for (watch, title, _, currency), prices in zip(PRODUCTS, series, strict=True):
            offer = Offer(watch.url, title, prices[day], currency, watch.url, available=not (watch.name ==
                          "Espresso machine" and 15 <= day <= 18))  # fmt: skip
            for event in changes(watch, offer, db.last_price(watch.id, offer.key), watch_is_new=day == 0,
                                 threshold_percent=5):  # fmt: skip
                db.record_event(event, at)
            db.record(watch.id, offer, at)
        offers = []
        for key, (title, price, appears) in listings.items():
            if day >= appears:
                trend = 1 - 0.003 * day + random.uniform(-0.01, 0.01)
                offers.append(Offer(key, title, Decimal(round(price * trend, -2)), "USD", f"https://example.com/{key}"))
        for offer in offers:
            for event in changes(SEARCH, offer, db.last_price(SEARCH.id, offer.key), watch_is_new=day == 0,
                                 threshold_percent=5):  # fmt: skip
                db.record_event(event, at)
            db.record(SEARCH.id, offer, at)
        db.record_search_stats(SEARCH.id, at, offers)
    db.commit()
    path = report.write(settings, [p[0] for p in PRODUCTS] + [SEARCH], db)
    db.close()
    print(f"Demo dashboard: {path}")


if __name__ == "__main__":
    main()
