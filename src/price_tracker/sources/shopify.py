"""Shopify stores. Every Shopify store exposes product data as JSON, so no HTML parsing is needed:
/products/<handle>.js for one product, /products.json or /collections/<name>/products.json for a catalog.
"""

import re
from decimal import Decimal
from urllib.parse import urlsplit

from price_tracker.models import Offer
from price_tracker.sources.base import Fetcher, SourceError

PRODUCT_PATH = re.compile(r"(?:/collections/[^/]+)?/products/([^/?#.]+)")
COLLECTION_PATH = re.compile(r"/collections/([^/?#]+)")


def _base(url: str) -> str:
    parts = urlsplit(url if "://" in url else f"https://{url}")
    return f"{parts.scheme}://{parts.netloc}"


_currencies: dict[str, str] = {}


def store_currency(fetcher: Fetcher, base: str) -> str:
    """Shopify publishes the store's currency at /meta.json. Cached per store."""
    if base not in _currencies:
        try:
            _currencies[base] = fetcher.get(f"{base}/meta.json").json().get("currency", "")
        except (SourceError, ValueError):
            _currencies[base] = ""
    return _currencies[base]


def fetch_product(fetcher: Fetcher, url: str, currency: str = "") -> Offer:
    match = PRODUCT_PATH.search(urlsplit(url).path)
    if not match:
        raise SourceError(f"Not a Shopify product URL (expected /products/<handle>): {url}")
    handle = match.group(1)
    response = fetcher.get(f"{_base(url)}/products/{handle}.js")
    try:
        data = response.json()
    except ValueError as exc:
        raise SourceError("The store did not return Shopify product JSON. Is it a Shopify store?") from exc
    variants = data.get("variants") or []
    in_stock = [v for v in variants if v.get("available")]
    cents = min((v["price"] for v in in_stock), default=data.get("price"))
    return Offer(
        key=handle,
        title=data.get("title", handle),
        price=Decimal(cents) / 100 if cents is not None else None,
        currency=currency or store_currency(fetcher, _base(url)),
        url=f"{_base(url)}/products/{handle}",
        available=bool(data.get("available", in_stock)),
        extracted_by="shopify",
    )


def search(fetcher: Fetcher, url: str, currency: str = "", max_results: int = 200) -> list[Offer]:
    """All products of a store, or of one collection if the URL points to /collections/<name>."""
    base = _base(url)
    collection = COLLECTION_PATH.search(urlsplit(url).path)
    endpoint = f"{base}/collections/{collection.group(1)}/products.json" if collection else f"{base}/products.json"
    currency = currency or store_currency(fetcher, base)
    offers: list[Offer] = []
    page = 1
    while len(offers) < max_results:
        try:
            products = fetcher.get(endpoint, params={"limit": 250, "page": page}).json().get("products", [])
        except ValueError as exc:
            raise SourceError("The store did not return Shopify catalog JSON. Is it a Shopify store?") from exc
        if not products:
            break
        for product in products:
            variants = product.get("variants") or []
            in_stock = [v for v in variants if v.get("available")]
            prices = [Decimal(v["price"]) for v in (in_stock or variants) if v.get("price")]
            offers.append(Offer(
                key=product["handle"],
                title=product.get("title", product["handle"]),
                price=min(prices) if prices else None,
                currency=currency,
                url=f"{base}/products/{product['handle']}",
                available=bool(in_stock),
                extracted_by="shopify",
            ))  # fmt: skip
        page += 1
    return offers[:max_results]
