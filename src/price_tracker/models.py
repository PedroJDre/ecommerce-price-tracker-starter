from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class Offer:
    """One product's price at one moment, from any source."""

    key: str  # stable id inside a watch: a URL, a Shopify handle, a Mercado Libre item id
    title: str
    price: Decimal | None
    currency: str
    url: str
    available: bool = True
    extracted_by: str = ""  # which method found the price: json-ld, meta, shopify, llm...


@dataclass
class Watch:
    """Something to track: a single product page, or a search that returns many listings."""

    name: str
    kind: str  # "product" or "search"
    source: str  # "page", "shopify", "mercadolibre"
    url: str = ""
    query: str = ""
    site: str = "MLA"  # Mercado Libre site: MLA Argentina, MLB Brazil, MLM Mexico...
    currency: str = ""
    target_price: Decimal | None = None
    include: list[str] = field(default_factory=list)  # search: every word must be in the title
    exclude: list[str] = field(default_factory=list)  # search: none of these words in the title
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    max_results: int = 200

    @property
    def id(self) -> str:
        return self.name.strip().lower().replace(" ", "-")


@dataclass
class Event:
    """Something worth telling someone about."""

    watch: str
    type: str  # price_drop, price_up, below_target, back_in_stock, out_of_stock, new_listing
    title: str
    url: str
    old_price: Decimal | None = None
    new_price: Decimal | None = None
    currency: str = ""

    @property
    def change_percent(self) -> float | None:
        if self.old_price and self.new_price is not None:
            return float((self.new_price - self.old_price) / self.old_price * 100)
        return None
