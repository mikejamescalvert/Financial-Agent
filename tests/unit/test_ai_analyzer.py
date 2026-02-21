"""Tests for AI analyzer response parsing."""

from financial_agent.analysis.ai_analyzer import AIAnalyzer
from financial_agent.portfolio.models import AssetClass, SignalType


class TestAIResponseParsing:
    """Test the JSON parsing logic without making API calls."""

    def _make_analyzer(self):
        """Create an analyzer instance for testing parse logic only."""
        # We only test _parse_response, which doesn't need valid API keys
        from unittest.mock import MagicMock

        analyzer = object.__new__(AIAnalyzer)
        analyzer._client = MagicMock()
        analyzer._model = "test"
        analyzer._max_tokens = 1024
        analyzer._strategy = "balanced"
        return analyzer

    def test_parse_valid_response(self):
        analyzer = self._make_analyzer()
        raw = """
        {
          "analysis_summary": "Market looks bullish",
          "signals": [
            {
              "symbol": "AAPL",
              "signal": "buy",
              "confidence": 0.75,
              "reason": "Strong momentum and positive MACD crossover",
              "target_weight": 0.08,
              "stop_loss": 170.0,
              "take_profit": 200.0
            },
            {
              "symbol": "MSFT",
              "signal": "hold",
              "confidence": 0.5,
              "reason": "Mixed signals, RSI neutral"
            }
          ]
        }
        """
        signals = analyzer._parse_response(raw)
        assert len(signals) == 2
        assert signals[0].symbol == "AAPL"
        assert signals[0].signal == SignalType.BUY
        assert signals[0].confidence == 0.75
        assert signals[1].signal == SignalType.HOLD

    def test_parse_code_fenced_response(self):
        analyzer = self._make_analyzer()
        raw = """```json
        {
          "analysis_summary": "Test",
          "signals": [
            {"symbol": "AAPL", "signal": "sell", "confidence": 0.8, "reason": "Overbought"}
          ]
        }
        ```"""
        signals = analyzer._parse_response(raw)
        assert len(signals) == 1
        assert signals[0].signal == SignalType.SELL

    def test_parse_invalid_json(self):
        analyzer = self._make_analyzer()
        signals = analyzer._parse_response("this is not json")
        assert signals == []

    def test_parse_missing_fields(self):
        analyzer = self._make_analyzer()
        raw = '{"signals": [{"symbol": "AAPL"}]}'
        signals = analyzer._parse_response(raw)
        assert len(signals) == 0  # Should skip invalid entries

    def test_crypto_symbol_gets_crypto_asset_class(self):
        analyzer = self._make_analyzer()
        raw = """
        {
          "analysis_summary": "Crypto bullish",
          "signals": [
            {
              "symbol": "BTC/USD",
              "signal": "buy",
              "confidence": 0.7,
              "reason": "Bullish momentum"
            },
            {
              "symbol": "AAPL",
              "signal": "hold",
              "confidence": 0.5,
              "reason": "Neutral"
            }
          ]
        }
        """
        signals = analyzer._parse_response(raw)
        assert len(signals) == 2
        assert signals[0].asset_class == AssetClass.CRYPTO
        assert signals[1].asset_class == AssetClass.US_EQUITY
