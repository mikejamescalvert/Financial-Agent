"""Pydantic models for market data enrichment."""

from __future__ import annotations

from datetime import date  # noqa: TCH003

from pydantic import BaseModel, Field


class FundamentalData(BaseModel):
    """Fundamental financial metrics for a single symbol."""

    eps_ttm: float | None = None
    pe_ratio: float | None = None
    revenue_growth: float | None = None
    profit_margin: float | None = None
    debt_to_equity: float | None = None
    free_cash_flow: float | None = None
    price_to_book: float | None = None
    market_cap: float | None = None


class EarningsEvent(BaseModel):
    """An upcoming earnings event for a symbol."""

    symbol: str
    earnings_date: date
    days_until_earnings: int
    eps_estimate: float | None = None


class NewsItem(BaseModel):
    """A single news article with sentiment."""

    headline: str
    sentiment_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    source: str = ""
    published_at: str = ""


class NewsSentiment(BaseModel):
    """Aggregated news sentiment for a symbol."""

    symbol: str
    items: list[NewsItem] = Field(default_factory=list)
    avg_sentiment: float = 0.0
    headline_count: int = 0


class MacroContext(BaseModel):
    """Macro-economic context data."""

    vix_level: float | None = None
    vix_trend: str = "stable"
    spy_trend: str = "neutral"
    ten_year_yield: float | None = None
    market_regime: str = "neutral"
    upcoming_events: list[str] = Field(default_factory=list)


class CryptoMarketContext(BaseModel):
    """Crypto market structure data."""

    btc_dominance: float | None = None
    fear_greed_index: int | None = None
    fear_greed_label: str = "neutral"
    btc_trend: str = "neutral"
    total_market_cap: float | None = None


class MarketEnrichment(BaseModel):
    """Top-level aggregation of all market enrichment data."""

    fundamentals: dict[str, FundamentalData] = Field(default_factory=dict)
    earnings: list[EarningsEvent] = Field(default_factory=list)
    news: dict[str, NewsSentiment] = Field(default_factory=dict)
    macro: MacroContext | None = None
    crypto: CryptoMarketContext | None = None
