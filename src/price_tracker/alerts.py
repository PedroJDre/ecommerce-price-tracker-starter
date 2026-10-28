"""Send events to Telegram, Slack/Discord (webhook) or email. Secrets come from environment variables."""

import logging
import smtplib
from email.message import EmailMessage

import httpx

from price_tracker.config import secret
from price_tracker.models import Event
from price_tracker.prices import format_price

log = logging.getLogger(__name__)

DEFAULT_EVENTS = ["price_drop", "below_target", "back_in_stock", "new_listing"]
LABELS = {
    "price_drop": "📉 Price drop",
    "price_up": "📈 Price up",
    "below_target": "🎯 Below your target",
    "back_in_stock": "✅ Back in stock",
    "out_of_stock": "⛔ Out of stock",
    "new_listing": "🆕 New listing",
}


def describe(event: Event) -> str:
    price = format_price(event.new_price, event.currency)
    if event.old_price is not None and event.new_price is not None and event.old_price != event.new_price:
        price = f"{format_price(event.old_price, event.currency)} → {price} ({event.change_percent:+.1f}%)"
    return f"{LABELS.get(event.type, event.type)} · {event.watch}\n{event.title}\n{price}\n{event.url}"


def message(events: list[Event], limit: int = 25) -> str:
    lines = [describe(e) for e in events[:limit]]
    if len(events) > limit:
        lines.append(f"…and {len(events) - limit} more. See the dashboard.")
    return "\n\n".join(lines)


def send(events: list[Event], config: dict, client: httpx.Client | None = None) -> list[str]:
    """Send the events each channel cares about. Returns the channels that were used."""
    wanted = set(config.get("events", DEFAULT_EVENTS))
    events = [e for e in events if e.type in wanted]
    if not events:
        return []
    text = message(events)
    client = client or httpx.Client(timeout=20)
    used = []

    if config.get("console", True):
        print(text)
        used.append("console")

    if config.get("telegram"):
        token, chat = secret("TELEGRAM_BOT_TOKEN"), secret("TELEGRAM_CHAT_ID")
        if token and chat:
            r = client.post(f"https://api.telegram.org/bot{token}/sendMessage",
                            json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True})  # fmt: skip
            if _check(r, "Telegram"):
                used.append("telegram")
        else:
            log.warning("Telegram is on but TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are missing.")

    if config.get("webhook"):
        url = secret("ALERT_WEBHOOK_URL")
        if url:
            # Discord expects "content"; Slack and most others accept "text".
            body = {"content": text[:1900]} if "discord" in url else {"text": text}
            if _check(client.post(url, json=body), "webhook"):
                used.append("webhook")
        else:
            log.warning("Webhook alerts are on but ALERT_WEBHOOK_URL is missing.")

    if config.get("email"):
        host, to = secret("SMTP_HOST"), secret("ALERT_EMAIL_TO")
        if host and to:
            mail = EmailMessage()
            mail["Subject"] = f"Price tracker: {len(events)} change(s)"
            mail["From"] = secret("SMTP_FROM") or secret("SMTP_USER")
            mail["To"] = to
            mail.set_content(text)
            with smtplib.SMTP(host, int(secret("SMTP_PORT") or 587), timeout=30) as smtp:
                smtp.starttls()
                if secret("SMTP_USER"):
                    smtp.login(secret("SMTP_USER"), secret("SMTP_PASSWORD"))
                smtp.send_message(mail)
            used.append("email")
        else:
            log.warning("Email alerts are on but SMTP_HOST / ALERT_EMAIL_TO are missing.")
    return used


def _check(response: httpx.Response, name: str) -> bool:
    if response.status_code >= 400:
        log.error("%s alert failed (HTTP %s): %s", name, response.status_code, response.text[:300])
        return False
    return True
