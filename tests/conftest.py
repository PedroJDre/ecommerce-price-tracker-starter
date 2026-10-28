import json
from pathlib import Path

import pytest
import respx

from price_tracker.config import Settings
from price_tracker.db import Database
from price_tracker.sources import shopify
from price_tracker.sources.base import Fetcher


@pytest.fixture
def fetcher():
    return Fetcher("test-agent", delay_seconds=0)


@pytest.fixture
def db():
    database = Database(":memory:")
    yield database
    database.close()


@pytest.fixture
def settings(tmp_path: Path):
    return Settings(database=tmp_path / "prices.db", report=tmp_path / "index.html", delay_seconds=0)


@pytest.fixture(autouse=True)
def clear_currency_cache():
    shopify._currencies.clear()


@pytest.fixture
def http():
    with respx.mock(assert_all_called=False) as mock:
        yield mock


def product_page(price="49.99", currency="USD", availability="InStock", name="Trail Shoe") -> str:
    data = {"@context": "https://schema.org", "@type": "Product", "name": name,
            "offers": {"@type": "Offer", "price": price, "priceCurrency": currency,
                       "availability": f"https://schema.org/{availability}"}}  # fmt: skip
    return f'<html><head><script type="application/ld+json">{json.dumps(data)}</script></head><body></body></html>'


def shopify_products(*items: tuple[str, str, bool]) -> dict:
    """items: (handle, price, available)"""
    return {"products": [
        {"handle": h, "title": h.replace("-", " ").title(), "variants": [{"price": p, "available": a}]}
        for h, p, a in items
    ]}  # fmt: skip
