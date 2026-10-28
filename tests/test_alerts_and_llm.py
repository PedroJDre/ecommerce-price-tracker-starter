import json
from decimal import Decimal

from price_tracker import alerts
from price_tracker.models import Event
from price_tracker.sources.llm import LLMExtractor, PriceExtraction

DROP = Event("Shoes", "price_drop", "Trail Shoe", "https://shop.test/shoe", Decimal("100"), Decimal("80"), "USD")
UP = Event("Shoes", "price_up", "Trail Shoe", "https://shop.test/shoe", Decimal("80"), Decimal("100"), "USD")


def test_message_text():
    text = alerts.describe(DROP)
    assert "Price drop" in text and "US$ 100 → US$ 80 (-20.0%)" in text and "https://shop.test/shoe" in text


def test_only_wanted_events_are_sent(capsys):
    assert alerts.send([UP], {"console": True}) == []  # price_up is not in the defaults
    assert alerts.send([DROP, UP], {"console": True}) == ["console"]
    assert "Price up" not in capsys.readouterr().out


def test_webhook_and_telegram(http, monkeypatch):
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://discord.com/api/webhooks/1/x")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    discord = http.post("https://discord.com/api/webhooks/1/x").respond(204)
    telegram = http.post("https://api.telegram.org/bot123:abc/sendMessage").respond(200, json={"ok": True})
    used = alerts.send([DROP], {"console": False, "webhook": True, "telegram": True})
    assert used == ["telegram", "webhook"]
    assert "content" in json.loads(discord.calls[0].request.content)
    assert json.loads(telegram.calls[0].request.content)["chat_id"] == "42"


def test_missing_secrets_skip_channel(monkeypatch):
    monkeypatch.delenv("ALERT_WEBHOOK_URL", raising=False)
    assert alerts.send([DROP], {"console": False, "webhook": True}) == []


class FakeModel:
    """Stands in for a LangChain chat model: returns a fixed structured answer."""

    def __init__(self, answer: PriceExtraction):
        self.answer = answer

    def with_structured_output(self, schema):
        return self

    def invoke(self, prompt):
        return self.answer


PAGE = "Lámpara Nórdica Antes $ 59.999 Ahora $ 45.999 o 6 cuotas de $ 7.666 Envío gratis"


def test_llm_fallback_reads_price():
    llm = LLMExtractor(FakeModel(PriceExtraction(found=True, title="Lámpara Nórdica", price_text="$ 45.999")))
    found = llm.extract(PAGE)
    assert found["price"] == Decimal("45999") and found["method"] == "llm"


def test_llm_made_up_price_is_rejected():
    llm = LLMExtractor(FakeModel(PriceExtraction(found=True, title="Lámpara", price_text="$ 42.000")))
    assert llm.extract(PAGE) is None


def test_llm_not_found():
    assert LLMExtractor(FakeModel(PriceExtraction(found=False))).extract(PAGE) is None
