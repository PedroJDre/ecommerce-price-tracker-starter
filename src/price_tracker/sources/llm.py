"""Optional fallback: when a page has no structured price data, ask an LLM to read the page text.

Install with `uv sync --extra llm` and set llm_fallback = true. The model's answer is never trusted
blindly: the exact price text it returns must appear on the page, or the result is discarded.
"""

import re

from pydantic import BaseModel, Field

from price_tracker.prices import detect_currency, parse_price

PROMPT = """Below is the visible text of an online store's product page. Find the main product's current
selling price (the price a customer pays now, not the old crossed-out price, not installments, not
shipping). Copy the price exactly as it is written on the page into price_text.
If there is no clear single product price, set found to false.

PAGE TEXT:
{text}"""


class PriceExtraction(BaseModel):
    found: bool = Field(description="True only if the page clearly shows one current price for the main product")
    title: str = Field(default="", description="Product name")
    price_text: str = Field(default="", description="The price copied exactly as written on the page, e.g. '$ 45.999'")
    currency: str = Field(default="", description="ISO currency code if known, e.g. ARS, USD, EUR")
    in_stock: bool = Field(default=True)


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


class LLMExtractor:
    def __init__(self, model):
        """model: a "provider:model" string or any LangChain chat model."""
        if isinstance(model, str):
            from langchain.chat_models import init_chat_model

            model = init_chat_model(model, temperature=0)
        self.chain = model.with_structured_output(PriceExtraction)

    def extract(self, page_text: str) -> dict | None:
        result: PriceExtraction = self.chain.invoke(PROMPT.format(text=page_text))
        if not result.found or not result.price_text:
            return None
        # Guardrail: the price must be copied from the page, not made up.
        if _squash(result.price_text) not in _squash(page_text):
            return None
        price = parse_price(result.price_text)
        if price is None or price <= 0:
            return None
        return {
            "title": result.title,
            "price": price,
            "currency": result.currency.upper() or detect_currency(result.price_text),
            "available": result.in_stock,
            "method": "llm",
        }
