"""Mercado Libre, through its official API.

The search API needs an access token (it answers 403 without one): create an app at developers.mercadolibre.com,
get a token, and set MELI_ACCESS_TOKEN. Scraping the website instead gets blocked quickly
and needs paid proxies, so this starter uses the API on purpose.
"""

import re
from decimal import Decimal

from price_tracker.config import secret
from price_tracker.models import Offer
from price_tracker.sources.base import Fetcher, SourceError

API = "https://api.mercadolibre.com"
ITEM_ID = re.compile(r"\b(M[A-Z]{2})-?(\d{6,})\b")
PAGE_SIZE = 50
MAX_OFFSET = 1000  # the API does not page past this


def _headers() -> dict:
    token = secret("MELI_ACCESS_TOKEN")
    if not token:
        raise SourceError("Mercado Libre needs an API token: set MELI_ACCESS_TOKEN (see README).")
    return {"Authorization": f"Bearer {token}"}


def _offer(item: dict) -> Offer:
    price = item.get("price")
    return Offer(
        key=item["id"],
        title=item.get("title", item["id"]),
        price=Decimal(str(price)) if price is not None else None,
        currency=item.get("currency_id", ""),
        url=item.get("permalink", ""),
        available=item.get("available_quantity", 1) > 0 and item.get("status", "active") == "active",
        extracted_by="mercadolibre",
    )


def fetch_product(fetcher: Fetcher, url: str, currency: str = "") -> Offer:
    match = ITEM_ID.search(url.upper())
    if not match:
        raise SourceError(f"No Mercado Libre item id (like MLA-123456789) in {url}")
    item_id = match.group(1) + match.group(2)
    return _offer(fetcher.get(f"{API}/items/{item_id}", headers=_headers()).json())


def search(fetcher: Fetcher, query: str, site: str = "MLA", max_results: int = 200) -> list[Offer]:
    offers: list[Offer] = []
    offset = 0
    while len(offers) < max_results and offset < MAX_OFFSET:
        data = fetcher.get(f"{API}/sites/{site}/search", headers=_headers(),
                           params={"q": query, "offset": offset, "limit": PAGE_SIZE}).json()  # fmt: skip
        results = data.get("results", [])
        offers += [_offer(item) for item in results]
        total = data.get("paging", {}).get("total", 0)
        offset += PAGE_SIZE
        if not results or offset >= total:
            break
    return offers[:max_results]
