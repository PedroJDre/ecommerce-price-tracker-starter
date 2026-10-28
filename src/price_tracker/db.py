"""SQLite price history. One file, easy to commit from GitHub Actions or copy anywhere."""

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from price_tracker.models import Event, Offer

SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    watch TEXT NOT NULL, key TEXT NOT NULL, title TEXT, url TEXT,
    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
    PRIMARY KEY (watch, key)
);
CREATE TABLE IF NOT EXISTS prices (
    watch TEXT NOT NULL, key TEXT NOT NULL, checked_at TEXT NOT NULL,
    price TEXT, currency TEXT, available INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS search_stats (
    watch TEXT NOT NULL, checked_at TEXT NOT NULL, count INTEGER NOT NULL,
    min TEXT, median TEXT, max TEXT, currency TEXT
);
CREATE TABLE IF NOT EXISTS events (
    watch TEXT NOT NULL, created_at TEXT NOT NULL, type TEXT NOT NULL, title TEXT, url TEXT,
    old_price TEXT, new_price TEXT, currency TEXT
);
CREATE TABLE IF NOT EXISTS errors (
    watch TEXT NOT NULL, created_at TEXT NOT NULL, message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prices ON prices (watch, key, checked_at);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _dec(value: str | None) -> Decimal | None:
    return Decimal(value) if value not in (None, "") else None


def _str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


class Database:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    # --- writes --------------------------------------------------------
    def record(self, watch: str, offer: Offer, at: str) -> None:
        self.conn.execute(
            """INSERT INTO offers (watch, key, title, url, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (watch, key) DO UPDATE SET title = excluded.title, url = excluded.url,
               last_seen = excluded.last_seen""",
            (watch, offer.key, offer.title, offer.url, at, at),
        )
        self.conn.execute(
            "INSERT INTO prices (watch, key, checked_at, price, currency, available) VALUES (?, ?, ?, ?, ?, ?)",
            (watch, offer.key, at, _str(offer.price), offer.currency, int(offer.available)),
        )

    def record_search_stats(self, watch: str, at: str, offers: list[Offer]) -> None:
        prices = sorted(o.price for o in offers if o.price is not None and o.available)
        median = prices[len(prices) // 2] if prices else None
        currency = next((o.currency for o in offers if o.currency), "")
        self.conn.execute(
            "INSERT INTO search_stats (watch, checked_at, count, min, median, max, currency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (watch, at, len(offers), _str(prices[0] if prices else None), _str(median),
             _str(prices[-1] if prices else None), currency),
        )  # fmt: skip

    def record_event(self, event: Event, at: str) -> None:
        self.conn.execute(
            "INSERT INTO events (watch, created_at, type, title, url, old_price, new_price, currency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event.watch, at, event.type, event.title, event.url, _str(event.old_price),
             _str(event.new_price), event.currency),
        )  # fmt: skip

    def record_error(self, watch: str, message: str, at: str) -> None:
        self.conn.execute("INSERT INTO errors (watch, created_at, message) VALUES (?, ?, ?)", (watch, at, message))

    def commit(self) -> None:
        self.conn.commit()

    # --- reads ---------------------------------------------------------
    def last_price(self, watch: str, key: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM prices WHERE watch = ? AND key = ? ORDER BY checked_at DESC, rowid DESC LIMIT 1",
            (watch, key),
        ).fetchone()

    def has_history(self, watch: str) -> bool:
        return self.conn.execute("SELECT 1 FROM prices WHERE watch = ? LIMIT 1", (watch,)).fetchone() is not None

    def history(self, watch: str, key: str) -> list[tuple[str, Decimal | None, bool]]:
        rows = self.conn.execute(
            "SELECT checked_at, price, available FROM prices WHERE watch = ? AND key = ? ORDER BY checked_at, rowid",
            (watch, key),
        ).fetchall()
        return [(r["checked_at"], _dec(r["price"]), bool(r["available"])) for r in rows]

    def latest_offers(self, watch: str) -> list[dict]:
        """Every offer seen in the watch's latest check, with its first recorded price."""
        last = self.conn.execute("SELECT MAX(checked_at) FROM prices WHERE watch = ?", (watch,)).fetchone()[0]
        if last is None:
            return []
        rows = self.conn.execute(
            """SELECT o.key, o.title, o.url, o.first_seen, p.price, p.currency, p.available,
                      (SELECT p2.price FROM prices p2 WHERE p2.watch = p.watch AND p2.key = p.key
                       ORDER BY p2.checked_at, p2.rowid LIMIT 1) AS first_price,
                      (SELECT MIN(CAST(p3.price AS REAL)) FROM prices p3
                       WHERE p3.watch = p.watch AND p3.key = p.key AND p3.price IS NOT NULL) AS lowest
               FROM prices p JOIN offers o ON o.watch = p.watch AND o.key = p.key
               WHERE p.watch = ? AND p.checked_at = ?""",
            (watch, last),
        ).fetchall()
        return [
            {**dict(r), "price": _dec(r["price"]), "first_price": _dec(r["first_price"]),
             "lowest": Decimal(str(r["lowest"])) if r["lowest"] is not None else None}
            for r in rows
        ]  # fmt: skip

    def search_stats(self, watch: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM search_stats WHERE watch = ? ORDER BY checked_at", (watch,)).fetchall()

    def recent_events(self, limit: int = 40) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM events ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
        ).fetchall()

    def last_error(self, watch: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM errors WHERE watch = ? ORDER BY created_at DESC, rowid DESC LIMIT 1", (watch,)
        ).fetchone()
