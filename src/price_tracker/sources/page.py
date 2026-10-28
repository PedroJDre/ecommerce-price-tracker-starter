"""Any product page. Reads the structured data most stores publish for Google Shopping:
JSON-LD (schema.org Product), Open Graph product tags and microdata. Works on most Shopify,
WooCommerce, VTEX, Tiendanube and Magento stores without writing a single CSS selector.
"""

import json
from decimal import Decimal

from bs4 import BeautifulSoup

from price_tracker.models import Offer
from price_tracker.prices import parse_price
from price_tracker.sources.base import Fetcher, SourceError


def _walk_json_ld(node):
    """Yield every dict in a JSON-LD tree (handles lists and @graph)."""
    if isinstance(node, list):
        for item in node:
            yield from _walk_json_ld(item)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                yield from _walk_json_ld(node[key])


def _as_list(value) -> list:
    if not value:
        return []
    return list(value) if isinstance(value, list) else [value]


def _is_type(node: dict, name: str) -> bool:
    types = node.get("@type", [])
    return name in (types if isinstance(types, list) else [types])


def _from_json_ld(soup: BeautifulSoup) -> dict | None:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _walk_json_ld(data):
            if not (_is_type(node, "Product") or _is_type(node, "ProductGroup")):
                continue
            offers = _as_list(node.get("offers"))
            for variant in _as_list(node.get("hasVariant")):  # ProductGroup: offers live on each variant
                if isinstance(variant, dict):
                    offers += _as_list(variant.get("offers"))
            prices, currency, available = [], "", None
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                price = parse_price(offer.get("price") or offer.get("lowPrice"))
                if price is None and isinstance(offer.get("priceSpecification"), dict):
                    price = parse_price(offer["priceSpecification"].get("price"))
                if price is not None:
                    prices.append(price)
                    currency = currency or offer.get("priceCurrency", "")
                stock = str(offer.get("availability", ""))
                if stock:
                    in_stock = "InStock" in stock or "PreOrder" in stock or "LimitedAvailability" in stock
                    available = bool(available) or in_stock
            if prices:
                return {"title": node.get("name"), "price": min(prices), "currency": currency,
                        "available": True if available is None else available, "method": "json-ld"}  # fmt: skip
    return None


def _meta(soup: BeautifulSoup, *names: str) -> str | None:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return tag["content"]
    return None


def _from_meta(soup: BeautifulSoup) -> dict | None:
    price = parse_price(_meta(soup, "product:price:amount", "og:price:amount"))
    if price is None:
        return None
    stock = (_meta(soup, "product:availability", "og:availability") or "").lower()
    return {"title": _meta(soup, "og:title"), "price": price,
            "currency": _meta(soup, "product:price:currency", "og:price:currency") or "",
            "available": not stock or "out" not in stock, "method": "meta"}  # fmt: skip


def _from_microdata(soup: BeautifulSoup) -> dict | None:
    tag = soup.find(attrs={"itemprop": "price"})
    if not tag:
        return None
    price = parse_price(tag.get("content") or tag.get_text())
    if price is None:
        return None
    currency_tag = soup.find(attrs={"itemprop": "priceCurrency"})
    currency = (currency_tag.get("content") or currency_tag.get_text()) if currency_tag else ""
    stock_tag = soup.find(attrs={"itemprop": "availability"})
    stock = (stock_tag.get("href") or stock_tag.get("content") or "") if stock_tag else ""
    return {"title": None, "price": price, "currency": currency.strip(), "available": "OutOfStock" not in stock,
            "method": "microdata"}  # fmt: skip


def extract(html: str) -> dict | None:
    """Price data from a product page, or None if the page publishes none."""
    soup = BeautifulSoup(html, "html.parser")
    for strategy in (_from_json_ld, _from_meta, _from_microdata):
        found = strategy(soup)
        if found:
            if not found.get("title"):
                found["title"] = _meta(soup, "og:title") or (soup.title.get_text(strip=True) if soup.title else "")
            return found
    return None


def page_text(html: str, limit: int = 8000) -> str:
    """Visible text of a page, for the optional LLM fallback."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())
    return text[:limit]


def fetch_product(fetcher: Fetcher, url: str, currency: str = "", llm=None) -> Offer:
    html = fetcher.get(url).text
    found = extract(html)
    if found is None and llm is not None:
        found = llm.extract(page_text(html))
    if found is None:
        raise SourceError(
            "No price data found on the page. It may load prices with JavaScript; "
            "enable llm_fallback or use the store's own source (for example 'shopify')."
        )
    price: Decimal = found["price"]
    return Offer(
        key=url,
        title=(found.get("title") or url).strip(),
        price=price,
        currency=found.get("currency") or currency,
        url=url,
        available=found.get("available", True),
        extracted_by=found["method"],
    )
