"""Tests for market data enrichment models."""

from __future__ import annotations

from datetime import date

from financial_agent.data.models import (
    CryptoMarketContext,
    EarningsEvent,
    FundamentalData,
    MacroContext,
    MarketEnrichment,
    NewsItem,
    NewsSentiment,
)


class TestMarketEnrichment:
    def test_creation_with_defaults(self):
        enrichment = MarketEnrichment()
        assert enrichment.fundamentals == {}
        assert enrichment.earnings == []
        assert enrichment.news == {}
        assert enrichment.macro is None
        assert enrichment.crypto is None

    def test_creation_with_macro_and_crypto(self):
        enrichment = MarketEnrichment(
            macro=MacroContext(),
            crypto=CryptoMarketContext(),
        )
        assert enrichment.macro is not None
        assert enrichment.crypto is not None

    def test_creation_with_fundamentals(self):
        enrichment = MarketEnrichment(
            fundamentals={"AAPL": FundamentalData(pe_ratio=25.0)},
        )
        assert "AAPL" in enrichment.fundamentals
        assert enrichment.fundamentals["AAPL"].pe_ratio == 25.0


class TestFundamentalData:
    def test_all_none_defaults(self):
        data = FundamentalData()
        assert data.eps_ttm is None
        assert data.pe_ratio is None
        assert data.revenue_growth is None
        assert data.profit_margin is None
        assert data.debt_to_equity is None
        assert data.free_cash_flow is None
        assert data.price_to_book is None
        assert data.market_cap is None

    def test_with_some_values(self):
        data = FundamentalData(
            eps_ttm=6.5,
            pe_ratio=28.0,
            market_cap=3e12,
        )
        assert data.eps_ttm == 6.5
        assert data.pe_ratio == 28.0
        assert data.market_cap == 3e12
        assert data.revenue_growth is None

    def test_all_values_set(self):
        data = FundamentalData(
            eps_ttm=5.0,
            pe_ratio=20.0,
            revenue_growth=0.12,
            profit_margin=0.25,
            debt_to_equity=1.5,
            free_cash_flow=1e9,
            price_to_book=8.0,
            market_cap=2e12,
        )
        assert data.eps_ttm == 5.0
        assert data.debt_to_equity == 1.5


class TestEarningsEvent:
    def test_creation(self):
        event = EarningsEvent(
            symbol="AAPL",
            earnings_date=date(2026, 4, 25),
            days_until_earnings=5,
        )
        assert event.symbol == "AAPL"
        assert event.earnings_date == date(2026, 4, 25)
        assert event.days_until_earnings == 5
        assert event.eps_estimate is None

    def test_creation_with_eps_estimate(self):
        event = EarningsEvent(
            symbol="MSFT",
            earnings_date=date(2026, 7, 15),
            days_until_earnings=10,
            eps_estimate=2.35,
        )
        assert event.eps_estimate == 2.35
        assert event.symbol == "MSFT"


class TestNewsItem:
    def test_defaults(self):
        item = NewsItem(headline="Stock goes up")
        assert item.headline == "Stock goes up"
        assert item.sentiment_score == 0.0
        assert item.source == ""
        assert item.published_at == ""

    def test_with_all_fields(self):
        item = NewsItem(
            headline="AAPL beats earnings",
            sentiment_score=0.8,
            source="Reuters",
            published_at="2026-02-20T10:00:00Z",
        )
        assert item.sentiment_score == 0.8
        assert item.source == "Reuters"


class TestNewsSentiment:
    def test_defaults(self):
        ns = NewsSentiment(symbol="AAPL")
        assert ns.symbol == "AAPL"
        assert ns.items == []
        assert ns.avg_sentiment == 0.0
        assert ns.headline_count == 0

    def test_with_items(self):
        items = [
            NewsItem(headline="Good news", sentiment_score=0.5),
            NewsItem(headline="Bad news", sentiment_score=-0.3),
        ]
        ns = NewsSentiment(
            symbol="AAPL",
            items=items,
            avg_sentiment=0.1,
            headline_count=2,
        )
        assert len(ns.items) == 2
        assert ns.avg_sentiment == 0.1
        assert ns.headline_count == 2


class TestMacroContext:
    def test_defaults(self):
        ctx = MacroContext()
        assert ctx.vix_level is None
        assert ctx.vix_trend == "stable"
        assert ctx.spy_trend == "neutral"
        assert ctx.ten_year_yield is None
        assert ctx.market_regime == "neutral"
        assert ctx.upcoming_events == []

    def test_with_values(self):
        ctx = MacroContext(
            vix_level=18.5,
            vix_trend="rising",
            spy_trend="bullish",
            ten_year_yield=4.25,
            market_regime="risk_on",
            upcoming_events=["FOMC", "NFP"],
        )
        assert ctx.vix_level == 18.5
        assert ctx.vix_trend == "rising"
        assert len(ctx.upcoming_events) == 2


class TestCryptoMarketContext:
    def test_defaults(self):
        ctx = CryptoMarketContext()
        assert ctx.btc_dominance is None
        assert ctx.fear_greed_index is None
        assert ctx.fear_greed_label == "neutral"
        assert ctx.btc_trend == "neutral"
        assert ctx.total_market_cap is None

    def test_with_values(self):
        ctx = CryptoMarketContext(
            btc_dominance=52.3,
            fear_greed_index=75,
            fear_greed_label="greed",
            btc_trend="bullish",
            total_market_cap=2.5e12,
        )
        assert ctx.btc_dominance == 52.3
        assert ctx.fear_greed_index == 75
        assert ctx.fear_greed_label == "greed"
        assert ctx.total_market_cap == 2.5e12
