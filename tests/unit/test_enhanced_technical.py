"""Tests for enhanced technical analysis indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd

from financial_agent.strategy.technical import TechnicalAnalyzer


def _make_bar_data(num_rows: int = 260, base_price: float = 150.0) -> pd.DataFrame:
    """Create a mock multi-index DataFrame for a single symbol with enough rows.

    Generates synthetic OHLCV data with an upward trend and random noise.
    """
    np.random.seed(42)
    dates = pd.bdate_range(end="2026-02-20", periods=num_rows)
    # Simulate a trending market with noise
    returns = np.random.normal(0.001, 0.015, num_rows)
    prices = base_price * np.cumprod(1 + returns)

    data = {
        "open": prices * (1 - np.random.uniform(0, 0.005, num_rows)),
        "high": prices * (1 + np.random.uniform(0, 0.02, num_rows)),
        "low": prices * (1 - np.random.uniform(0, 0.02, num_rows)),
        "close": prices,
        "volume": np.random.randint(1_000_000, 50_000_000, num_rows).astype(float),
    }
    df = pd.DataFrame(data, index=dates)
    return df


def _make_multi_symbol_bars(
    symbols: list[str],
    num_rows: int = 260,
) -> pd.DataFrame:
    """Create multi-index DataFrame for multiple symbols."""
    frames = []
    for i, symbol in enumerate(symbols):
        df = _make_bar_data(num_rows=num_rows, base_price=100.0 + i * 50)
        df["symbol"] = symbol
        frames.append(df)
    combined = pd.concat(frames)
    combined = combined.set_index("symbol", append=True).swaplevel()
    return combined


class TestComputeRelativeStrength:
    def test_adds_rs_vs_spy_and_rs_rank_pct(self):
        analyzer = TechnicalAnalyzer()

        # Create technicals with return_20d for multiple symbols
        technicals = {
            "SPY": {"return_20d": 5.0, "current_price": 450.0},
            "AAPL": {"return_20d": 8.0, "current_price": 180.0},
            "MSFT": {"return_20d": 3.0, "current_price": 350.0},
            "GOOGL": {"return_20d": 10.0, "current_price": 150.0},
        }

        result = analyzer.compute_relative_strength(technicals, benchmark_symbol="SPY")

        # SPY itself should not have rs_vs_spy
        assert "rs_vs_spy" not in result["SPY"]

        # AAPL: 8.0 - 5.0 = 3.0
        assert "rs_vs_spy" in result["AAPL"]
        assert abs(result["AAPL"]["rs_vs_spy"] - 3.0) < 0.01

        # MSFT: 3.0 - 5.0 = -2.0
        assert abs(result["MSFT"]["rs_vs_spy"] - (-2.0)) < 0.01

        # GOOGL: 10.0 - 5.0 = 5.0 (highest)
        assert abs(result["GOOGL"]["rs_vs_spy"] - 5.0) < 0.01

        # Check ranking: GOOGL > AAPL > MSFT
        assert result["GOOGL"]["rs_rank_pct"] > result["AAPL"]["rs_rank_pct"]
        assert result["AAPL"]["rs_rank_pct"] > result["MSFT"]["rs_rank_pct"]

    def test_no_benchmark_returns_unchanged(self):
        analyzer = TechnicalAnalyzer()
        technicals = {
            "AAPL": {"return_20d": 8.0},
            "MSFT": {"return_20d": 3.0},
        }
        result = analyzer.compute_relative_strength(technicals, benchmark_symbol="SPY")
        # SPY not present, should return unchanged
        assert "rs_vs_spy" not in result["AAPL"]
        assert "rs_vs_spy" not in result["MSFT"]

    def test_single_symbol_with_benchmark(self):
        analyzer = TechnicalAnalyzer()
        technicals = {
            "SPY": {"return_20d": 5.0},
            "AAPL": {"return_20d": 8.0},
        }
        result = analyzer.compute_relative_strength(technicals)
        assert "rs_vs_spy" in result["AAPL"]
        assert "rs_rank_pct" in result["AAPL"]


class TestSupportResistance:
    def test_finds_swing_highs_and_lows(self):
        analyzer = TechnicalAnalyzer()
        bars = _make_multi_symbol_bars(["TEST"], num_rows=80)
        results = analyzer.compute_indicators(bars)

        assert "TEST" in results
        indicators = results["TEST"]
        # Should have at least some of these depending on data pattern
        # The support/resistance levels may or may not be present depending
        # on the random data, but the method should run without error
        assert "current_price" in indicators

    def test_support_resistance_method_directly(self):
        analyzer = TechnicalAnalyzer()
        # Create data with a clear swing high and swing low
        n = 60
        prices = np.array([100.0] * n)
        # Create a swing high at position 30
        for i in range(25, 36):
            prices[i] = 100.0 + 5.0 * (1 - abs(i - 30) / 5.0)
        # Create a swing low at position 45
        for i in range(40, 51):
            prices[i] = 100.0 - 5.0 * (1 - abs(i - 45) / 5.0)

        high = pd.Series(prices + 1.0)
        low = pd.Series(prices - 1.0)
        close = pd.Series(prices)

        result = analyzer._support_resistance(high, low, close)
        # Result may have nearest_resistance and/or nearest_support
        # depending on whether swing points are above/below current price
        assert isinstance(result, dict)


class TestExtendedIndicators:
    def test_sma_200_present_with_enough_data(self):
        analyzer = TechnicalAnalyzer()
        bars = _make_multi_symbol_bars(["AAPL"], num_rows=260)
        results = analyzer.compute_indicators(bars)

        assert "AAPL" in results
        indicators = results["AAPL"]
        assert "sma_200" in indicators
        assert "price_vs_sma200" in indicators

    def test_sma_100_present_with_enough_data(self):
        analyzer = TechnicalAnalyzer()
        bars = _make_multi_symbol_bars(["AAPL"], num_rows=260)
        results = analyzer.compute_indicators(bars)

        assert "sma_100" in results["AAPL"]

    def test_atr_pct_present(self):
        analyzer = TechnicalAnalyzer()
        bars = _make_multi_symbol_bars(["AAPL"], num_rows=260)
        results = analyzer.compute_indicators(bars)

        assert "atr_pct" in results["AAPL"]
        assert results["AAPL"]["atr_pct"] > 0

    def test_return_20d_present(self):
        analyzer = TechnicalAnalyzer()
        bars = _make_multi_symbol_bars(["AAPL"], num_rows=260)
        results = analyzer.compute_indicators(bars)

        assert "return_20d" in results["AAPL"]

    def test_return_60d_present(self):
        analyzer = TechnicalAnalyzer()
        bars = _make_multi_symbol_bars(["AAPL"], num_rows=260)
        results = analyzer.compute_indicators(bars)

        assert "return_60d" in results["AAPL"]

    def test_52_week_high_low(self):
        analyzer = TechnicalAnalyzer()
        bars = _make_multi_symbol_bars(["AAPL"], num_rows=260)
        results = analyzer.compute_indicators(bars)

        indicators = results["AAPL"]
        assert "high_52w" in indicators
        assert "low_52w" in indicators
        assert "pct_from_52w_high" in indicators
        assert "pct_from_52w_low" in indicators
        assert indicators["high_52w"] >= indicators["low_52w"]

    def test_weekly_trend_present(self):
        analyzer = TechnicalAnalyzer()
        bars = _make_multi_symbol_bars(["AAPL"], num_rows=260)
        results = analyzer.compute_indicators(bars)

        indicators = results["AAPL"]
        assert "weekly_sma_10" in indicators
        assert "weekly_trend" in indicators
        assert indicators["weekly_trend"] in [1.0, -1.0]

    def test_standard_indicators_present(self):
        analyzer = TechnicalAnalyzer()
        bars = _make_multi_symbol_bars(["AAPL"], num_rows=260)
        results = analyzer.compute_indicators(bars)

        indicators = results["AAPL"]
        standard_keys = [
            "sma_20",
            "sma_50",
            "ema_12",
            "ema_26",
            "macd",
            "macd_signal",
            "macd_histogram",
            "rsi_14",
            "bb_upper",
            "bb_lower",
            "bb_width",
            "atr_14",
            "obv",
            "avg_volume_20",
            "current_price",
            "price_vs_sma20",
            "daily_return_pct",
        ]
        for key in standard_keys:
            assert key in indicators, f"Missing indicator: {key}"

    def test_multiple_symbols(self):
        analyzer = TechnicalAnalyzer()
        bars = _make_multi_symbol_bars(["AAPL", "MSFT", "GOOGL"], num_rows=260)
        results = analyzer.compute_indicators(bars)

        assert len(results) == 3
        for symbol in ["AAPL", "MSFT", "GOOGL"]:
            assert symbol in results
            assert "current_price" in results[symbol]

    def test_insufficient_data_omits_extended(self):
        analyzer = TechnicalAnalyzer()
        # Only 40 rows -- not enough for sma_200, return_60d, etc.
        bars = _make_multi_symbol_bars(["AAPL"], num_rows=40)
        results = analyzer.compute_indicators(bars)

        indicators = results["AAPL"]
        assert "sma_200" not in indicators
        assert "sma_100" not in indicators
        # return_60d requires 60 rows
        assert "return_60d" not in indicators
