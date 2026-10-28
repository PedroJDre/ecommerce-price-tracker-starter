from decimal import Decimal
from pathlib import Path

import httpx

from price_tracker import config, report, tracker
from price_tracker.models import Offer, Watch
from tests.conftest import product_page, shopify_products

PRODUCT = Watch(name="Trail Shoe", kind="product", source="page", url="https://shop.test/shoe",
                target_price=Decimal("40"))  # fmt: skip
SEARCH = Watch(name="Store runners", kind="search", source="shopify", url="https://store.test",
               include=["runner"], exclude=["sock"])  # fmt: skip


def run(settings, db, fetcher):
    return tracker.run(settings, [PRODUCT, SEARCH], db, fetcher)


def types(result):
    return sorted((e.type, e.title) for e in result.events)


def test_tracks_changes_across_runs(http, settings, db, fetcher):
    shoe = http.get("https://shop.test/shoe")
    catalog = http.get("https://store.test/products.json")
    http.get("https://store.test/meta.json").respond(json={"currency": "USD"})

    # Run 1: first look. Nothing to report yet.
    shoe.respond(200, text=product_page("49.99"))
    catalog.side_effect = [
        httpx.Response(200, json=shopify_products(("tree-runner", "100.00", True), ("wool-runner", "110.00", False),
                                                  ("runner-sock", "15.00", True), ("cap", "30.00", True))),
        httpx.Response(200, json={"products": []}),
    ]  # fmt: skip
    first = run(settings, db, fetcher)
    assert first.errors == {} and first.events == []
    assert first.checked == {"Trail Shoe": 1, "Store runners": 2}  # sock and cap filtered out

    # Run 2: the shoe drops under the target, a runner is back in stock, another drops, one is new.
    shoe.respond(200, text=product_page("38.00"))
    catalog.side_effect = [
        httpx.Response(200, json=shopify_products(("tree-runner", "80.00", True), ("wool-runner", "110.00", True),
                                                  ("dasher-runner", "125.00", True))),
        httpx.Response(200, json={"products": []}),
    ]  # fmt: skip
    second = run(settings, db, fetcher)
    assert types(second) == [
        ("back_in_stock", "Wool Runner"),
        ("below_target", "Trail Shoe"),
        ("new_listing", "Dasher Runner"),
        ("price_drop", "Trail Shoe"),
        ("price_drop", "Tree Runner"),
    ]

    # Run 3: same prices again. No repeated alerts.
    catalog.side_effect = [
        httpx.Response(200, json=shopify_products(("tree-runner", "80.00", True), ("wool-runner", "110.00", True),
                                                  ("dasher-runner", "125.00", True))),
        httpx.Response(200, json={"products": []}),
    ]  # fmt: skip
    assert run(settings, db, fetcher).events == []

    html = report.render(settings, [PRODUCT, SEARCH], db)
    assert "Trail Shoe" in html and "<polyline" in html and "Dasher Runner" in html
    assert "Below your target" in html


def test_small_moves_are_ignored(http, settings, db, fetcher):
    shoe = http.get("https://shop.test/shoe")
    shoe.respond(200, text=product_page("100"))
    tracker.run(settings, [PRODUCT], db, fetcher)
    shoe.respond(200, text=product_page("97"))  # -3%, under the 5% threshold
    assert tracker.run(settings, [PRODUCT], db, fetcher).events == []


def test_one_failing_watch_does_not_stop_the_rest(http, settings, db, fetcher):
    http.get("https://shop.test/shoe").respond(403)
    http.get("https://store.test/meta.json").respond(json={"currency": "USD"})
    http.get("https://store.test/products.json").side_effect = [
        httpx.Response(200, json=shopify_products(("tree-runner", "100.00", True))),
        httpx.Response(200, json={"products": []}),
    ]
    result = run(settings, db, fetcher)
    assert "blocked" in result.errors["Trail Shoe"]
    assert result.checked == {"Store runners": 1}
    assert "Last check failed" in report.render(settings, [PRODUCT, SEARCH], db)


def test_empty_search_is_an_error_not_a_sellout(http, settings, db, fetcher):
    http.get("https://store.test/meta.json").respond(json={"currency": "USD"})
    http.get("https://store.test/products.json").respond(json={"products": []})
    result = tracker.run(settings, [SEARCH], db, fetcher)
    assert "no listings" in result.errors["Store runners"]


def test_filters():
    watch = Watch(name="w", kind="search", source="shopify", include=["baic", "x55"], exclude=["repuesto"],
                  min_price=Decimal("5000"), max_price=Decimal("50000"))  # fmt: skip

    def offer(title, price):
        return Offer(key=title, title=title, price=Decimal(price), currency="USD", url="")

    assert tracker.keep(watch, offer("BAIC X55 Plus 2024", "32000"))
    assert not tracker.keep(watch, offer("Baic X55 repuesto óptica", "300"))
    assert not tracker.keep(watch, offer("Baic BJ30", "41000"))
    assert not tracker.keep(watch, offer("Baic X55", "900"))
    assert not tracker.keep(watch, offer("Baic X55", "90000"))


def test_example_watchlist_is_valid():
    settings, watches = config.load(Path(__file__).resolve().parent.parent / "watchlist.example.toml")
    assert [w.kind for w in watches] == ["product", "product", "search"]
    assert settings.alerts["console"] is True
    assert watches[0].target_price == Decimal("80")


def test_config_errors(tmp_path):
    bad = tmp_path / "w.toml"
    bad.write_text('[[search]]\nname = "x"\nsource = "page"\nurl = "https://a.test"\n')
    try:
        config.load(bad)
    except config.ConfigError as exc:
        assert "shopify or mercadolibre" in str(exc)
    else:
        raise AssertionError("expected ConfigError")
