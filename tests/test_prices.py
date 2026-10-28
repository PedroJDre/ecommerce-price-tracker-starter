from decimal import Decimal

import pytest

from price_tracker.prices import detect_currency, format_price, parse_price


@pytest.mark.parametrize("text,expected", [
    ("$ 1.234,56", "1234.56"),
    ("US$ 1,299.99", "1299.99"),
    ("£51.77", "51.77"),
    ("$ 45.999", "45999"),
    ("$45,999", "45999"),
    ("1.250.000", "1250000"),
    ("12,5 €", "12.5"),
    ("1 299,00 €", "1299.00"),
    ("R$ 2.499,90", "2499.90"),
    ("Precio: $ 89.000 en 6 cuotas", "89000"),
    ("100", "100"),
    (49.99, "49.99"),
    (10000, "10000"),
])  # fmt: skip
def test_parse_price(text, expected):
    assert parse_price(text) == Decimal(expected)


@pytest.mark.parametrize("text", [None, "", "Consultar", "Sin stock", True])
def test_parse_price_nothing(text):
    assert parse_price(text) is None


def test_detect_currency():
    assert detect_currency("US$ 100") == "USD"
    assert detect_currency("AR$ 100") == "ARS"
    assert detect_currency("R$ 100") == "BRL"
    assert detect_currency("£5") == "GBP"
    assert detect_currency("$ 100", default="ARS") == "ARS"


def test_format_price():
    assert format_price(Decimal("1250000"), "ARS") == "$ 1,250,000"
    assert format_price(Decimal("51.77"), "GBP") == "£ 51.77"
    assert format_price(None) == "—"
