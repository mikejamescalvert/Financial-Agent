"""Tests for watchlist reviewer response parsing and prompt building."""

from datetime import datetime
from unittest.mock import MagicMock

from financial_agent.portfolio.models import AssetClass, PortfolioSnapshot, Position
from financial_agent.review.watchlist_reviewer import WatchlistReviewer


class TestWatchlistParsing:
    """Test the JSON parsing logic without making API calls."""

    def _make_reviewer(self):
        """Create a reviewer instance for testing parse logic only."""
        reviewer = object.__new__(WatchlistReviewer)
        reviewer._client = MagicMock()
        reviewer._model = "test"
        reviewer._max_tokens = 4096
        reviewer._trading_config = MagicMock()
        return reviewer

    def test_parse_valid_response(self):
        reviewer = self._make_reviewer()
        raw = """
        {
          "summary": "Strong tech momentum, rotating into growth names.",
          "stock_watchlist": ["AAPL", "NVDA", "MSFT", "AMZN", "META", "CRM", "AVGO", "AMD"],
          "crypto_watchlist": ["BTC/USD", "ETH/USD", "SOL/USD"],
          "changes": [
            {"symbol": "CRM", "action": "add", "reason": "Strong MACD crossover"},
            {"symbol": "JNJ", "action": "remove", "reason": "Weak momentum, RSI declining"},
            {"symbol": "AAPL", "action": "keep", "reason": "Steady uptrend"}
          ]
        }
        """
        result = reviewer._parse_response(raw)
        assert result["summary"] == "Strong tech momentum, rotating into growth names."
        assert len(result["stock_watchlist"]) == 8
        assert "NVDA" in result["stock_watchlist"]
        assert len(result["crypto_watchlist"]) == 3
        assert len(result["changes"]) == 3
        assert result["changes"][0]["action"] == "add"

    def test_parse_code_fenced_response(self):
        reviewer = self._make_reviewer()
        raw = """```json
        {
          "summary": "Market neutral.",
          "stock_watchlist": ["AAPL", "MSFT"],
          "crypto_watchlist": ["BTC/USD"],
          "changes": []
        }
        ```"""
        result = reviewer._parse_response(raw)
        assert result["stock_watchlist"] == ["AAPL", "MSFT"]
        assert result["crypto_watchlist"] == ["BTC/USD"]

    def test_parse_invalid_json(self):
        reviewer = self._make_reviewer()
        result = reviewer._parse_response("not valid json!!!")
        assert result["stock_watchlist"] == []
        assert result["crypto_watchlist"] == []
        assert result["changes"] == []

    def test_parse_empty_watchlists(self):
        reviewer = self._make_reviewer()
        raw = """
        {
          "summary": "No good candidates.",
          "stock_watchlist": [],
          "crypto_watchlist": [],
          "changes": []
        }
        """
        result = reviewer._parse_response(raw)
        assert result["stock_watchlist"] == []
        assert result["crypto_watchlist"] == []


class TestWatchlistPrompt:
    """Test the prompt building logic."""

    def _make_reviewer_with_config(self):
        reviewer = object.__new__(WatchlistReviewer)
        reviewer._client = MagicMock()
        reviewer._model = "test"
        reviewer._max_tokens = 4096

        config = MagicMock()
        config.strategy = "balanced"
        config.watchlist = "AAPL,MSFT,NVDA"
        config.crypto_watchlist = "BTC/USD,ETH/USD"
        config.stock_universe = "AAPL,MSFT,NVDA,AMZN,GOOGL"
        config.crypto_universe = "BTC/USD,ETH/USD,SOL/USD"
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
            ]
        return PortfolioSnapshot(
            equity=10000.0,
            cash=5000.0,
            buying_power=10000.0,
            positions=positions,
            timestamp=datetime(2026, 1, 15, 12, 0),
        )

    def test_prompt_includes_current_watchlists(self):
        reviewer = self._make_reviewer_with_config()
        portfolio = self._make_portfolio()
        prompt = reviewer._build_prompt(portfolio, {})
        assert "AAPL" in prompt
        assert "MSFT" in prompt
        assert "BTC/USD" in prompt

    def test_prompt_includes_held_positions(self):
        reviewer = self._make_reviewer_with_config()
        portfolio = self._make_portfolio()
        prompt = reviewer._build_prompt(portfolio, {})
        assert "DO NOT remove" in prompt
        assert "AAPL" in prompt

    def test_prompt_includes_strategy(self):
        reviewer = self._make_reviewer_with_config()
        portfolio = self._make_portfolio()
        prompt = reviewer._build_prompt(portfolio, {})
        assert "balanced" in prompt

    def test_prompt_includes_technicals(self):
        reviewer = self._make_reviewer_with_config()
        portfolio = self._make_portfolio()
        technicals = {
            "AAPL": {"rsi_14": 55.0, "sma_20": 165.0},
            "BTC/USD": {"rsi_14": 62.0, "sma_20": 42000.0},
        }
        prompt = reviewer._build_prompt(portfolio, technicals)
        assert "Stock Universe" in prompt
        assert "Crypto Universe" in prompt
        assert "rsi_14" in prompt

    def test_prompt_separates_stock_and_crypto_technicals(self):
        reviewer = self._make_reviewer_with_config()
        portfolio = self._make_portfolio()
        technicals = {
            "AAPL": {"rsi_14": 55.0},
            "MSFT": {"rsi_14": 60.0},
            "BTC/USD": {"rsi_14": 62.0},
        }
        prompt = reviewer._build_prompt(portfolio, technicals)
        # Stock and crypto sections should be separate
        stock_section_idx = prompt.index("Stock Universe")
        crypto_section_idx = prompt.index("Crypto Universe")
        assert stock_section_idx < crypto_section_idx

    def test_prompt_empty_portfolio(self):
        reviewer = self._make_reviewer_with_config()
        portfolio = self._make_portfolio(positions=[])
        prompt = reviewer._build_prompt(portfolio, {})
        assert "Positions: 0" in prompt
