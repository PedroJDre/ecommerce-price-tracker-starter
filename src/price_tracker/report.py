"""Static HTML dashboard (no JavaScript, no external files). Publish docs/ with GitHub Pages."""

from datetime import UTC, datetime
from decimal import Decimal
from html import escape
from pathlib import Path

from price_tracker.alerts import LABELS
from price_tracker.config import Settings
from price_tracker.db import Database
from price_tracker.models import Watch
from price_tracker.prices import format_price


def sparkline(*series: list[Decimal | None], width: int = 260, height: int = 56,
              classes: tuple[str, ...] = ("line", "alt")) -> str:  # fmt: skip
    """One or more lines on a shared scale, so they can be compared."""
    all_values = [float(v) for values in series for v in values if v is not None]
    svg = (f'<svg class="spark" viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
           f'style="height:{height}px" aria-hidden="true">')  # fmt: skip
    if len(all_values) < 2:
        return svg + "</svg>"
    lo, hi = min(all_values), max(all_values)
    span = (hi - lo) or 1
    for values, css in zip(series, classes, strict=False):
        last_index = max(len(values) - 1, 1)
        coords = [(i / last_index * (width - 8) + 4, height - 6 - (float(v) - lo) / span * (height - 12))
                  for i, v in enumerate(values) if v is not None]  # fmt: skip
        if len(coords) < 2:
            continue
        path = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
        cx, cy = coords[-1]
        svg += (f'<polyline class="{css}" points="{path}"/>'
                f'<polyline class="{css} dot" points="{cx:.1f},{cy:.1f} {cx:.1f},{cy:.1f}"/>')  # fmt: skip
    return svg + "</svg>"


def badge(old: Decimal | None, new: Decimal | None) -> str:
    if not old or new is None or old == new:
        return ""
    change = float((new - old) / old * 100)
    kind = "down" if change < 0 else "up"
    return f'<span class="badge {kind}">{change:+.1f}%</span>'


def when(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d %b %Y, %H:%M UTC")


def short_date(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d %b, %H:%M")


def _error_note(db: Database, watch: Watch, last_check: str | None) -> str:
    error = db.last_error(watch.id)
    if error and (last_check is None or error["created_at"] > last_check):
        return (
            f'<p class="error">Last check failed ({escape(when(error["created_at"]))}): {escape(error["message"])}</p>'
        )
    return ""


def product_card(db: Database, watch: Watch) -> str:
    offers = db.latest_offers(watch.id)
    if not offers:
        return (f'<article class="card"><h2>{escape(watch.name)}</h2><p class="muted">No data yet.</p>'
                f"{_error_note(db, watch, None)}</article>")  # fmt: skip
    o = offers[0]
    history = db.history(watch.id, o["key"])
    target = (f'<div><span>Target</span><b>{format_price(watch.target_price, o["currency"])}</b></div>'
              if watch.target_price is not None else "")  # fmt: skip
    stock = "" if o["available"] else '<span class="badge out">Out of stock</span>'
    return f"""<article class="card">
  <h2><a href="{escape(o["url"])}">{escape(watch.name)}</a></h2>
  <p class="muted">{escape(o["title"])}</p>
  <div class="price">{format_price(o["price"], o["currency"])} {badge(o["first_price"], o["price"])} {stock}</div>
  {sparkline([h[1] for h in history])}
  <div class="facts"><div><span>Lowest seen</span><b>{format_price(o["lowest"], o["currency"])}</b></div>
  <div><span>First seen</span><b>{format_price(o["first_price"], o["currency"])}</b></div>{target}
  <div><span>Checks</span><b>{len(history)}</b></div></div>
  {_error_note(db, watch, history[-1][0])}
</article>"""


def search_card(db: Database, watch: Watch) -> str:
    stats = db.search_stats(watch.id)
    if not stats:
        return (f'<article class="card wide"><h2>{escape(watch.name)}</h2><p class="muted">No data yet.</p>'
                f"{_error_note(db, watch, None)}</article>")  # fmt: skip
    last = stats[-1]
    currency = last["currency"] or watch.currency
    offers = sorted((o for o in db.latest_offers(watch.id) if o["price"] is not None and o["available"]),
                    key=lambda o: o["price"])  # fmt: skip
    rows = "".join(
        f'<tr><td><a href="{escape(o["url"])}">{escape(o["title"])}</a>'
        f"{' <span class="badge new">new</span>' if o['first_seen'] == last['checked_at'] and len(stats) > 1 else ''}</td>"
        f'<td class="num">{format_price(o["price"], o["currency"] or currency)} {badge(o["first_price"], o["price"])}</td></tr>'
        for o in offers[:10]
    )
    medians = [Decimal(s["median"]) if s["median"] else None for s in stats]
    mins = [Decimal(s["min"]) if s["min"] else None for s in stats]
    first_median = medians[0] if medians else None
    return f"""<article class="card wide">
  <h2>{escape(watch.name)}</h2>
  <p class="muted">{escape(watch.query or watch.url)} · {last["count"]} listings in the last check</p>
  <div class="split">
    <div>
      <div class="facts"><div><span>Median</span><b>{format_price(medians[-1], currency)} {badge(first_median, medians[-1])}</b></div>
      <div><span>Cheapest</span><b>{format_price(mins[-1], currency)}</b></div>
      <div><span>Most expensive</span><b>{format_price(Decimal(last["max"]) if last["max"] else None, currency)}</b></div></div>
      <p class="legend"><i class="line"></i> median <i class="alt"></i> cheapest</p>
      {sparkline(medians, mins, height=110)}
    </div>
    <div class="table"><table><thead><tr><th>Cheapest listings now</th><th class="num">Price</th></tr></thead>
    <tbody>{rows}</tbody></table></div>
  </div>
  {_error_note(db, watch, last["checked_at"])}
</article>"""


def _change(e) -> str:
    new = format_price(Decimal(e["new_price"]) if e["new_price"] else None, e["currency"])
    if not e["old_price"] or e["old_price"] == e["new_price"]:
        return new
    return f"{format_price(Decimal(e['old_price']), e['currency'])} → {new}"


def events_section(db: Database) -> str:
    rows = (
        "".join(
            f"<tr><td class='nowrap'>{escape(short_date(e['created_at']))}</td><td class='nowrap'>{LABELS.get(e['type'], e['type'])}</td>"
            f'<td><a href="{escape(e["url"] or "#")}">{escape(e["title"] or "")}</a></td>'
            f'<td class="num">{_change(e)}</td></tr>'
            for e in db.recent_events(15)
        )
        or '<tr><td colspan="4" class="muted">No changes yet. They appear from the second check on.</td></tr>'
    )
    return f'<section><h2 class="section">Recent changes</h2><div class="table card"><table><tbody>{rows}</tbody></table></div></section>'


CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#16191d;--muted:#5d6670;--line:#e4e7eb;--accent:#2563eb;--alt:#f59e0b;--down:#15803d;--up:#b91c1c;--down-bg:#dcfce7;--up-bg:#fee2e2}
@media (prefers-color-scheme:dark){:root{--bg:#0f1216;--card:#171b21;--ink:#e8eaed;--muted:#9aa3ad;--line:#2a3038;--accent:#60a5fa;--alt:#fbbf24;--down:#4ade80;--up:#f87171;--down-bg:#12301d;--up-bg:#3a1515}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:auto;padding:28px 16px 48px}header h1{margin:0;font-size:26px}header p{margin:4px 0 24px;color:var(--muted)}
a{color:inherit;text-decoration-color:var(--line);text-underline-offset:3px}a:hover{color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;min-width:0}.wide{grid-column:1/-1}
.card h2{margin:0;font-size:17px}.muted{color:var(--muted);margin:2px 0 10px;font-size:13.5px}
.price{font-size:28px;font-weight:700;font-variant-numeric:tabular-nums}
.facts{display:flex;flex-wrap:wrap;gap:6px 22px;margin-top:8px}.facts span{display:block;color:var(--muted);font-size:12px}.facts b{font-variant-numeric:tabular-nums}
.spark{width:100%;margin-top:10px;display:block}.line,.alt{fill:none;stroke-width:2.2;stroke-linejoin:round;stroke-linecap:round}
.line{stroke:var(--accent)}.alt{stroke:var(--alt)}.line,.alt{vector-effect:non-scaling-stroke}.dot{stroke-width:7}
.legend{font-size:12px;color:var(--muted);margin:12px 0 0}.legend i{display:inline-block;width:14px;height:3px;border-radius:2px;vertical-align:middle;margin:0 4px 0 8px}
.legend i.line{background:var(--accent)}.legend i.alt{background:var(--alt)}
.badge{display:inline-block;font-size:12px;font-weight:600;padding:1px 7px;border-radius:99px;vertical-align:middle}
.badge.down{color:var(--down);background:var(--down-bg)}.badge.up{color:var(--up);background:var(--up-bg)}.badge.out,.badge.new{color:var(--muted);border:1px solid var(--line)}
.split{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.4fr);gap:24px}@media (max-width:760px){.split{grid-template-columns:1fr}}
.table{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:14px}th{text-align:left;color:var(--muted);font-weight:500;font-size:12.5px}
td,th{padding:8px 6px;border-top:1px solid var(--line)}thead th{border-top:0}.nowrap{white-space:nowrap}.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.section{font-size:18px;margin:32px 0 12px}.error{color:var(--up);font-size:13px;margin:10px 0 0}footer{color:var(--muted);font-size:12.5px;margin-top:32px}
"""


def render(settings: Settings, watches: list[Watch], db: Database) -> str:
    cards = "".join(product_card(db, w) if w.kind == "product" else search_card(db, w) for w in watches)
    updated = datetime.now(UTC).strftime("%d %b %Y, %H:%M UTC")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(settings.title)}</title><style>{CSS}</style></head><body><main>
<header><h1>{escape(settings.title)}</h1><p>{len(watches)} watches · updated {updated}</p></header>
<div class="grid">{cards}</div>{events_section(db)}
<footer>Made with <a href="https://github.com/PedroJDre/ecommerce-price-tracker-starter">ecommerce-price-tracker-starter</a>.</footer>
</main></body></html>"""


def write(settings: Settings, watches: list[Watch], db: Database) -> Path:
    settings.report.parent.mkdir(parents=True, exist_ok=True)
    settings.report.write_text(render(settings, watches, db), encoding="utf-8")
    return settings.report
