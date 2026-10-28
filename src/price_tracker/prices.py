"""Turn price text from any store into a number: "$ 1.234,56", "£51.77", "US$ 1,299", "1 299,00 €"."""

import re
from decimal import Decimal, InvalidOperation

CURRENCY_SYMBOLS = {
    "US$": "USD", "U$S": "USD", "USD": "USD", "AR$": "ARS", "ARS": "ARS", "R$": "BRL", "BRL": "BRL",
    "€": "EUR", "EUR": "EUR", "£": "GBP", "GBP": "GBP", "MXN": "MXN", "CLP": "CLP", "COP": "COP",
}  # fmt: skip
NUMBER = re.compile(r"\d[\d.,\s  ']*")


def detect_currency(text: str, default: str = "") -> str:
    upper = text.upper()
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in upper:
            return code
    return default


def parse_price(value: str | int | float | Decimal | None) -> Decimal | None:
    """Parse a price, guessing the decimal separator from the text.

    With both "." and ",", the last one is the decimal separator. With only one kind, it is a
    thousands separator when 3 digits follow it or it repeats ("1.500", "1,500,000"); otherwise
    it is decimal ("51.77", "12,5").
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        return Decimal(str(value)) if value >= 0 else None
    match = NUMBER.search(str(value))
    if not match:
        return None
    raw = re.sub(r"[\s  ']", "", match.group(0)).rstrip(".,")
    if not raw:
        return None

    last_dot, last_comma = raw.rfind("."), raw.rfind(",")
    if last_dot >= 0 and last_comma >= 0:
        decimal_sep = "." if last_dot > last_comma else ","
    elif last_dot >= 0 or last_comma >= 0:
        sep = "." if last_dot >= 0 else ","
        decimals = len(raw) - raw.rfind(sep) - 1
        # "1.500" / "1,500" / "1.500.000" are thousands; "51.77" / "12,5" are decimals.
        decimal_sep = None if decimals == 3 or raw.count(sep) > 1 else sep
    else:
        decimal_sep = None

    if decimal_sep:
        thousands = "," if decimal_sep == "." else "."
        normalized = raw.replace(thousands, "").replace(decimal_sep, ".")
    else:
        normalized = raw.replace(".", "").replace(",", "")
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def format_price(amount: Decimal | float | None, currency: str = "") -> str:
    if amount is None:
        return "—"
    amount = Decimal(str(amount))
    whole = amount == amount.to_integral_value()
    text = f"{amount:,.0f}" if whole else f"{amount:,.2f}"
    symbol = {"USD": "US$", "ARS": "$", "EUR": "€", "GBP": "£", "BRL": "R$"}.get(currency, currency)
    return f"{symbol} {text}".strip()
