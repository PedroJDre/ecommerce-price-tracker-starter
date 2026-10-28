"""One run: check every watch, store prices, detect changes. A failing watch never stops the others."""

import logging
import unicodedata
from dataclasses import dataclass, field

from price_tracker.config import Settings
from price_tracker.db import Database, now
from price_tracker.detect import changes
from price_tracker.models import Event, Offer, Watch
from price_tracker.sources import mercadolibre, page, shopify
from price_tracker.sources.base import Fetcher, SourceError

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    events: list[Event] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    checked: dict[str, int] = field(default_factory=dict)  # watch name -> offers stored


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def keep(watch: Watch, offer: Offer) -> bool:
    """Search filters: drop accessories, parts and listings outside the price range."""
    title = _plain(offer.title)
    if any(_plain(w) not in title for w in watch.include):
        return False
    if any(_plain(w) in title for w in watch.exclude):
        return False
    if offer.price is None:
        return False
    if watch.min_price is not None and offer.price < watch.min_price:
        return False
    return watch.max_price is None or offer.price <= watch.max_price


def fetch(watch: Watch, fetcher: Fetcher, llm=None) -> list[Offer]:
    if watch.kind == "product":
        if watch.source == "shopify":
            return [shopify.fetch_product(fetcher, watch.url, watch.currency)]
        if watch.source == "mercadolibre":
            return [mercadolibre.fetch_product(fetcher, watch.url, watch.currency)]
        return [page.fetch_product(fetcher, watch.url, watch.currency, llm=llm)]
    if watch.source == "shopify":
        offers = shopify.search(fetcher, watch.url, watch.currency, max_results=10_000)
    else:
        offers = mercadolibre.search(fetcher, watch.query, watch.site, max_results=10_000)
    return [o for o in offers if keep(watch, o)][: watch.max_results]


def run(settings: Settings, watches: list[Watch], db: Database, fetcher: Fetcher | None = None,
        llm=None) -> RunResult:  # fmt: skip
    fetcher = fetcher or Fetcher(settings.user_agent, settings.delay_seconds, settings.timeout_seconds)
    if llm is None and settings.llm_fallback:
        from price_tracker.sources.llm import LLMExtractor  # optional dependency

        llm = LLMExtractor(settings.llm_model)

    result = RunResult()
    for watch in watches:
        at = now()
        try:
            offers = fetch(watch, fetcher, llm)
        except SourceError as exc:
            log.warning("%s: %s", watch.name, exc)
            result.errors[watch.name] = str(exc)
            db.record_error(watch.id, str(exc), at)
            continue
        if watch.kind == "search" and not offers:
            # An empty search usually means the store changed or blocked us, not that everything sold out.
            message = "The search returned no listings after filters; nothing was stored."
            result.errors[watch.name] = message
            db.record_error(watch.id, message, at)
            continue

        watch_is_new = not db.has_history(watch.id)
        seen: set[str] = set()
        for offer in offers:
            if offer.key in seen:
                continue
            seen.add(offer.key)
            for event in changes(watch, offer, db.last_price(watch.id, offer.key), watch_is_new=watch_is_new,
                                 threshold_percent=settings.drop_threshold_percent):  # fmt: skip
                result.events.append(event)
                db.record_event(event, at)
            db.record(watch.id, offer, at)
        if watch.kind == "search":
            db.record_search_stats(watch.id, at, offers)
        result.checked[watch.name] = len(seen)
        db.commit()
        log.info("%s: %d offer(s)", watch.name, len(seen))
    db.commit()
    return result
