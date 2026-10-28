"""Load the watchlist (TOML). See watchlist.example.toml."""

import os
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from price_tracker.models import Watch

SOURCES = {"page", "shopify", "mercadolibre"}


class ConfigError(ValueError):
    pass


@dataclass
class Settings:
    database: Path = Path("data/prices.db")
    report: Path = Path("docs/index.html")
    title: str = "Price tracker"
    drop_threshold_percent: float = 5.0  # smaller moves are ignored (noise, rounding)
    delay_seconds: float = 1.5  # pause between requests to the same store
    timeout_seconds: float = 20.0
    user_agent: str = "Mozilla/5.0 (compatible; price-tracker-starter/0.1; +https://github.com/PedroJDre/ecommerce-price-tracker-starter)"
    llm_fallback: bool = False
    llm_model: str = "anthropic:claude-haiku-5-5"
    alerts: dict = field(default_factory=dict)


def _decimal(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _watch(raw: dict, kind: str) -> Watch:
    name = raw.get("name")
    if not name:
        raise ConfigError(f"Every [[{kind}]] needs a name.")
    source = raw.get("source", "page" if kind == "product" else "")
    if source not in SOURCES:
        raise ConfigError(f"'{name}': source must be one of {sorted(SOURCES)}.")
    if kind == "product" and not raw.get("url"):
        raise ConfigError(f"'{name}': a product needs a url.")
    if kind == "search":
        if source == "page":
            raise ConfigError(f"'{name}': searches need a shopify or mercadolibre source.")
        if source == "shopify" and not raw.get("url"):
            raise ConfigError(f"'{name}': a Shopify search needs the store url (or a collection url).")
        if source == "mercadolibre" and not raw.get("query"):
            raise ConfigError(f"'{name}': a Mercado Libre search needs a query.")
    return Watch(
        name=name,
        kind=kind,
        source=source,
        url=raw.get("url", ""),
        query=raw.get("query", ""),
        site=raw.get("site", "MLA"),
        currency=raw.get("currency", ""),
        target_price=_decimal(raw.get("target_price")),
        include=[w.lower() for w in raw.get("include", [])],
        exclude=[w.lower() for w in raw.get("exclude", [])],
        min_price=_decimal(raw.get("min_price")),
        max_price=_decimal(raw.get("max_price")),
        max_results=int(raw.get("max_results", 200)),
    )


def load(path: Path | str) -> tuple[Settings, list[Watch]]:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"{path} not found. Copy watchlist.example.toml to {path.name} to start.")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    raw_settings = data.get("settings", {})
    settings = Settings(**{k: v for k, v in raw_settings.items() if k in Settings.__dataclass_fields__})
    settings.database, settings.report = Path(settings.database), Path(settings.report)
    settings.alerts = data.get("alerts", {})

    watches = [_watch(p, "product") for p in data.get("product", [])]
    watches += [_watch(s, "search") for s in data.get("search", [])]
    ids = [w.id for w in watches]
    if len(ids) != len(set(ids)):
        raise ConfigError("Watch names must be unique.")
    return settings, watches


def secret(name: str) -> str:
    """Secrets come from the environment (or GitHub Actions secrets), never from the watchlist."""
    return os.environ.get(name, "")
