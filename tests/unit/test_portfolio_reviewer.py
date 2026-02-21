"""Tests for portfolio reviewer response parsing and prompt building."""

from datetime import datetime
from unittest.mock import MagicMock

from financial_agent.portfolio.models import AssetClass, PortfolioSnapshot, Position
from financial_agent.review.reviewer import PortfolioReviewer


class TestReviewParsing:
    """Test the JSON parsing logic without making API calls."""

    def _make_reviewer(self):
        """Create a reviewer instance for testing parse logic only."""
        reviewer = object.__new__(PortfolioReviewer)
        reviewer._client = MagicMock()
        reviewer._model = "test"
        reviewer._max_tokens = 4096
        reviewer._trading_config = MagicMock()
        return reviewer

    def test_parse_valid_review(self):
        reviewer = self._make_reviewer()
        raw = """
        {
          "portfolio_grade": "B",
          "summary": "Portfolio is performing well but has concentration risk.",
          "suggestions": [
            {
              "title": "Reduce TSLA position size",
              "priority": "high",
              "category": "risk",
              "body": "TSLA is 15% of portfolio, exceeding the 10% max.",
              "labels": ["enhancement"]
            }
          ]
        }
        """
        result = reviewer._parse_review(raw)
        assert result["portfolio_grade"] == "B"
        assert "concentration" in result["summary"]
        assert len(result["suggestions"]) == 1
        assert result["suggestions"][0]["title"] == "Reduce TSLA position size"
        assert result["suggestions"][0]["priority"] == "high"

    def test_parse_code_fenced_review(self):
        reviewer = self._make_reviewer()
        raw = """```json
        {
          "portfolio_grade": "C",
          "summary": "Needs improvement.",
          "suggestions": [
            {
              "title": "Add stop losses",
              "priority": "high",
              "category": "strategy",
              "body": "No stop losses configured."
            }
          ]
        }
        ```"""
        result = reviewer._parse_review(raw)
        assert result["portfolio_grade"] == "C"
        assert len(result["suggestions"]) == 1

    def test_parse_invalid_json(self):
        reviewer = self._make_reviewer()
        result = reviewer._parse_review("this is not json at all")
        assert result["portfolio_grade"] == "?"
        assert result["suggestions"] == []

    def test_parse_empty_suggestions(self):
        reviewer = self._make_reviewer()
        raw = '{"portfolio_grade": "A", "summary": "All good.", "suggestions": []}'
        result = reviewer._parse_review(raw)
        assert result["portfolio_grade"] == "A"
        assert result["suggestions"] == []

    def test_parse_multiple_suggestions(self):
        reviewer = self._make_reviewer()
        raw = """
        {
          "portfolio_grade": "D",
          "summary": "Major issues found.",
          "suggestions": [
            {"title": "Fix A", "priority": "high", "category": "risk", "body": "Detail A"},
            {"title": "Fix B", "priority": "medium", "category": "config", "body": "Detail B"},
            {"title": "Fix C", "priority": "low", "category": "watchlist", "body": "Detail C"}
          ]
        }
        """
        result = reviewer._parse_review(raw)
        assert len(result["suggestions"]) == 3
        assert result["suggestions"][0]["priority"] == "high"
        assert result["suggestions"][2]["category"] == "watchlist"


class TestReviewPrompt:
    """Test the prompt building logic."""

    def _make_reviewer_with_config(self):
        reviewer = object.__new__(PortfolioReviewer)
        reviewer._client = MagicMock()
        reviewer._model = "test"
        reviewer._max_tokens = 4096

        config = MagicMock()
        config.strategy = "balanced"
        config.max_position_pct = 0.10
        config.stop_loss_pct = 0.05
        config.take_profit_pct = 0.15
        config.min_cash_reserve_pct = 0.10
        config.watchlist = "AAPL,MSFT"
        config.crypto_watchlist = "BTC/USD"
        config.max_daily_trades = 10
        reviewer._trading_config = config
        return reviewer

    def _make_portfolio(self, positions=None):
        if positions is None:
            positions = [
                Position(
                    symbol="AAPL",
                    qty=10,
                    avg_entry_price=150.0,
                    current_price=170.0,
                    market_value=1700.0,
                    unrealized_pl=200.0,
                    unrealized_pl_pct=0.1333,
                    asset_class=AssetClass.US_EQUITY,
                ),
                Position(
                    symbol="BTC/USD",
                    qty=0.5,
                    avg_entry_price=40000.0,
                    current_price=38000.0,
                    market_value=19000.0,
                    unrealized_pl=-1000.0,
                    unrealized_pl_pct=-0.05,
                    asset_class=AssetClass.CRYPTO,
                ),
            ]
        return PortfolioSnapshot(
            equity=25000.0,
            cash=4300.0,
            buying_power=8600.0,
            positions=positions,
            timestamp=datetime(2026, 1, 15, 12, 0),
        )

    def test_prompt_includes_portfolio_overview(self):
        reviewer = self._make_reviewer_with_config()
        portfolio = self._make_portfolio()
        prompt = reviewer._build_review_prompt(portfolio, {})
        assert "$25,000.00" in prompt
        assert "$4,300.00" in prompt
        assert "2" in prompt  # position count mentioned

    def test_prompt_separates_winners_and_losers(self):
        reviewer = self._make_reviewer_with_config()
        portfolio = self._make_portfolio()
        prompt = reviewer._build_review_prompt(portfolio, {})
        assert "Top Winners" in prompt
        assert "Top Losers" in prompt
        assert "AAPL" in prompt
        assert "BTC/USD" in prompt

    def test_prompt_includes_config(self):
        reviewer = self._make_reviewer_with_config()
        portfolio = self._make_portfolio()
        prompt = reviewer._build_review_prompt(portfolio, {})
        assert "balanced" in prompt
        assert "10%" in prompt  # max position
        assert "5.0%" in prompt  # stop loss

    def test_prompt_includes_technicals(self):
        reviewer = self._make_reviewer_with_config()
        portfolio = self._make_portfolio()
        technicals = {"AAPL": {"rsi_14": 55.1234, "sma_20": 165.5678}}
        prompt = reviewer._build_review_prompt(portfolio, technicals)
        assert "rsi_14" in prompt
        assert "sma_20" in prompt

    def test_prompt_empty_portfolio(self):
        reviewer = self._make_reviewer_with_config()
        portfolio = self._make_portfolio(positions=[])
        prompt = reviewer._build_review_prompt(portfolio, {})
        assert "Total positions: 0" in prompt
        assert "None" in prompt  # winners/losers should be "None"
