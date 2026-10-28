import json
from decimal import Decimal

import httpx
import pytest

from price_tracker.sources import mercadolibre, page, shopify
from price_tracker.sources.base import SourceError
from tests.conftest import product_page, shopify_products

# --- generic product pages ---------------------------------------------------------------


def test_json_ld_product():
    found = page.extract(product_page("1.299,90", "ARS"))
    assert found["price"] == Decimal("1299.90")
    assert found["currency"] == "ARS" and found["available"] and found["method"] == "json-ld"
    assert found["title"] == "Trail Shoe"


def test_json_ld_out_of_stock():
    assert page.extract(product_page(availability="OutOfStock"))["available"] is False


def test_json_ld_product_group_and_graph():
    data = {"@graph": [
        {"@type": "WebPage", "name": "ignored"},
        {"@type": "ProductGroup", "name": "Runner", "hasVariant": [
            {"@type": "Product", "offers": {"price": "120", "priceCurrency": "USD", "availability": "OutOfStock"}},
            {"@type": "Product", "offers": {"price": "95", "priceCurrency": "USD", "availability": "InStock"}},
        ]},
    ]}  # fmt: skip
    html = f'<script type="application/ld+json">{json.dumps(data)}</script>'
    found = page.extract(html)
    assert found["price"] == Decimal("95") and found["available"] and found["title"] == "Runner"


def test_aggregate_offer_low_price():
    data = {"@type": "Product", "name": "X", "offers": {"@type": "AggregateOffer", "lowPrice": 30, "highPrice": 50}}
    assert page.extract(f'<script type="application/ld+json">{json.dumps(data)}</script>')["price"] == Decimal("30")


def test_open_graph_meta():
    html = """<meta property="og:title" content="Mate"><meta property="product:price:amount" content="15000">
              <meta property="product:price:currency" content="ARS">"""
    found = page.extract(html)
    assert found == {"title": "Mate", "price": Decimal("15000"), "currency": "ARS", "available": True, "method": "meta"}


def test_microdata():
    html = """<title>Lamp</title><div itemscope itemtype="https://schema.org/Product">
      <span itemprop="price" content="89.50">$89.50</span><meta itemprop="priceCurrency" content="USD">
      <link itemprop="availability" href="https://schema.org/OutOfStock"></div>"""
    found = page.extract(html)
    assert found["price"] == Decimal("89.50") and found["currency"] == "USD"
    assert found["available"] is False and found["title"] == "Lamp"


def test_broken_json_ld_is_skipped():
    html = '<script type="application/ld+json">{not json</script><meta property="og:price:amount" content="10">'
    assert page.extract(html)["method"] == "meta"


def test_page_without_price(http, fetcher):
    http.get("https://shop.test/p").respond(200, text="<html><title>Hi</title></html>")
    with pytest.raises(SourceError, match="No price data"):
        page.fetch_product(fetcher, "https://shop.test/p")


def test_blocked_request(http, fetcher):
    http.get("https://shop.test/p").respond(403)
    with pytest.raises(SourceError, match="blocked"):
        page.fetch_product(fetcher, "https://shop.test/p")


def test_network_error(http, fetcher):
    http.get("https://shop.test/p").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(SourceError, match="Could not reach"):
        page.fetch_product(fetcher, "https://shop.test/p")


# --- Shopify -------------------------------------------------------------------------------


def test_shopify_product(http, fetcher):
    http.get("https://store.test/products/tee.js").respond(json={
        "title": "Tee", "price": 2500, "available": True,
        "variants": [{"price": 3000, "available": True}, {"price": 2500, "available": False}],
    })  # fmt: skip
    http.get("https://store.test/meta.json").respond(json={"currency": "EUR"})
    offer = shopify.fetch_product(fetcher, "https://store.test/collections/all/products/tee?variant=1")
    assert offer.key == "tee" and offer.currency == "EUR"
    assert offer.price == Decimal("30")  # cheapest variant that is in stock
    assert offer.url == "https://store.test/products/tee"


def test_shopify_collection_pages(http, fetcher):
    route = http.get("https://store.test/collections/sale/products.json")
    route.side_effect = [
        httpx.Response(200, json=shopify_products(("a", "10.00", True), ("b", "20.00", False))),
        httpx.Response(200, json=shopify_products(("c", "30.00", True))),
        httpx.Response(200, json={"products": []}),
    ]
    http.get("https://store.test/meta.json").respond(json={"currency": "USD"})
    offers = shopify.search(fetcher, "https://store.test/collections/sale")
    assert [(o.key, o.price, o.available) for o in offers] == [
        ("a", Decimal("10.00"), True), ("b", Decimal("20.00"), False), ("c", Decimal("30.00"), True)]  # fmt: skip
    assert {o.currency for o in offers} == {"USD"}


def test_not_shopify_url(fetcher):
    with pytest.raises(SourceError, match="Not a Shopify product URL"):
        shopify.fetch_product(fetcher, "https://store.test/item/123")


# --- Mercado Libre ---------------------------------------------------------------------------


def test_mercadolibre_needs_token(fetcher, monkeypatch):
    monkeypatch.delenv("MELI_ACCESS_TOKEN", raising=False)
    with pytest.raises(SourceError, match="MELI_ACCESS_TOKEN"):
        mercadolibre.search(fetcher, "baic")


def test_mercadolibre_search(http, fetcher, monkeypatch):
    monkeypatch.setenv("MELI_ACCESS_TOKEN", "tok")
    item = {"id": "MLA1", "title": "Baic X55", "price": 32000, "currency_id": "USD", "permalink": "https://ml/1",
            "available_quantity": 1}  # fmt: skip
    route = http.get("https://api.mercadolibre.com/sites/MLA/search")
    route.side_effect = [
        httpx.Response(200, json={"results": [item] * 50, "paging": {"total": 60}}),
        httpx.Response(200, json={"results": [{**item, "id": "MLA2"}] * 10, "paging": {"total": 60}}),
    ]
    offers = mercadolibre.search(fetcher, "baic")
    assert len(offers) == 60
    assert route.calls[0].request.headers["Authorization"] == "Bearer tok"
    assert route.calls[1].request.url.params["offset"] == "50"
    assert offers[0].price == Decimal("32000") and offers[0].currency == "USD"


def test_mercadolibre_item_from_url(http, fetcher, monkeypatch):
    monkeypatch.setenv("MELI_ACCESS_TOKEN", "tok")
    http.get("https://api.mercadolibre.com/items/MLA123456789").respond(json={
        "id": "MLA123456789", "title": "Baic BJ30", "price": 41000, "currency_id": "USD",
        "permalink": "https://auto.mercadolibre.com.ar/MLA-123456789-baic", "available_quantity": 0,
    })  # fmt: skip
    offer = mercadolibre.fetch_product(fetcher, "https://auto.mercadolibre.com.ar/MLA-123456789-baic-bj30-_JM")
    assert offer.key == "MLA123456789" and offer.available is False
