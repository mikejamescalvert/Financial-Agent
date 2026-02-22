"""Technical analysis indicators computed from historical price data."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ta  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import pandas as pd


class TechnicalAnalyzer:
    """Compute technical indicators for a set of symbols."""

    def compute_indicators(self, bars: pd.DataFrame) -> dict[str, dict[str, float]]:
        """Compute indicators per symbol from multi-index bar data.

        Returns a dict keyed by symbol with indicator values.
        """
        results: dict[str, dict[str, float]] = {}

        symbols = bars.index.get_level_values(0).unique()
        for symbol in symbols:
            try:
                df = bars.loc[symbol].copy()
                results[symbol] = self._indicators_for_symbol(df)
            except Exception:  # noqa: S112
                continue

        return results

    def _indicators_for_symbol(self, df: pd.DataFrame) -> dict[str, float]:
        """Calculate all indicators for a single symbol's bar data."""
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        indicators: dict[str, float] = {}

        # Trend indicators
        indicators["sma_20"] = ta.trend.sma_indicator(close, window=20).iloc[-1]
        indicators["sma_50"] = ta.trend.sma_indicator(close, window=50).iloc[-1]
        indicators["ema_12"] = ta.trend.ema_indicator(close, window=12).iloc[-1]
        indicators["ema_26"] = ta.trend.ema_indicator(close, window=26).iloc[-1]

        macd = ta.trend.MACD(close)
        indicators["macd"] = macd.macd().iloc[-1]
        indicators["macd_signal"] = macd.macd_signal().iloc[-1]
        indicators["macd_histogram"] = macd.macd_diff().iloc[-1]

        # Momentum indicators
        indicators["rsi_14"] = ta.momentum.rsi(close, window=14).iloc[-1]
        stoch = ta.momentum.StochasticOscillator(high, low, close)
        indicators["stoch_k"] = stoch.stoch().iloc[-1]
        indicators["stoch_d"] = stoch.stoch_signal().iloc[-1]

        # Volatility indicators
        bb = ta.volatility.BollingerBands(close)
        indicators["bb_upper"] = bb.bollinger_hband().iloc[-1]
        indicators["bb_lower"] = bb.bollinger_lband().iloc[-1]
        indicators["bb_width"] = bb.bollinger_wband().iloc[-1]
        indicators["atr_14"] = ta.volatility.average_true_range(high, low, close).iloc[-1]

        # Volume indicators
        indicators["obv"] = ta.volume.on_balance_volume(close, volume).iloc[-1]
        indicators["vwap"] = (close * volume).sum() / volume.sum()

        # Current price context
        indicators["current_price"] = close.iloc[-1]
        indicators["price_vs_sma20"] = (close.iloc[-1] / indicators["sma_20"] - 1) * 100
        indicators["daily_return_pct"] = ((close.iloc[-1] / close.iloc[-2]) - 1) * 100

        return indicators
