"""tracker run | tracker report | tracker check <url>"""

import argparse
import logging
import sys

from price_tracker import alerts, config, report, tracker
from price_tracker.db import Database
from price_tracker.models import Watch
from price_tracker.prices import format_price
from price_tracker.sources.base import Fetcher, SourceError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tracker", description="Track e-commerce prices.")
    parser.add_argument("-c", "--config", default="watchlist.toml", help="Watchlist file (default: watchlist.toml)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="Check every watch, store prices, send alerts, rebuild the dashboard")
    run_p.add_argument("--no-alerts", action="store_true")
    sub.add_parser("report", help="Rebuild the dashboard from stored data")
    check_p = sub.add_parser("check", help="Test one URL without storing anything")
    check_p.add_argument("url")
    check_p.add_argument("--source", default="page", choices=sorted(config.SOURCES))
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    if args.command == "check":
        return check(args.url, args.source)

    try:
        settings, watches = config.load(args.config)
    except config.ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    db = Database(settings.database)
    try:
        if args.command == "run":
            result = tracker.run(settings, watches, db)
            for name, count in result.checked.items():
                print(f"✓ {name}: {count} offer(s)")
            for name, error in result.errors.items():
                print(f"✗ {name}: {error}", file=sys.stderr)
            print(f"{len(result.events)} change(s) detected.")
            if not args.no_alerts:
                alerts.send(result.events, settings.alerts)
        path = report.write(settings, watches, db)
        print(f"Dashboard: {path}")
    finally:
        db.close()
    # Fail the run (and the GitHub Action) only when every watch failed.
    return 1 if args.command == "run" and watches and not result.checked else 0


def check(url: str, source: str) -> int:
    settings = config.Settings()
    fetcher = Fetcher(settings.user_agent, 0, settings.timeout_seconds)
    watch = Watch(name="check", kind="product", source=source, url=url)
    try:
        [offer] = tracker.fetch(watch, fetcher)
    except SourceError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(f"Title:     {offer.title}\nPrice:     {format_price(offer.price, offer.currency)}\n"
          f"Currency:  {offer.currency or '(unknown: set currency in the watchlist)'}\n"
          f"In stock:  {'yes' if offer.available else 'no'}\nFound via: {offer.extracted_by}")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
