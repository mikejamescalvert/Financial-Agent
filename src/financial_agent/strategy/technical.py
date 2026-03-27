"""Technical analysis indicators computed from historical price data."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import structlog
import ta  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import pandas as pd

log = structlog.get_logger()


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
            except (KeyError, ValueError, IndexError) as e:
                log.warning("indicator_calc_failed", symbol=symbol, error=str(e))
                continue

        return results

    def compute_relative_strength(
        self,
        technicals: dict[str, dict[str, float]],
        benchmark_symbol: str = "SPY",
    ) -> dict[str, dict[str, float]]:
        """Add relative strength metrics to existing technicals.

        Compares each symbol's momentum to the benchmark (SPY).
        Returns enriched technicals with rs_vs_spy and rs_rank fields.
        """
        benchmark = technicals.get(benchmark_symbol)
        if not benchmark:
            return technicals

        bench_return = benchmark.get("return_20d", 0.0)

        # Calculate relative strength for each symbol
        rs_scores: dict[str, float] = {}
        for symbol, indicators in technicals.items():
            if symbol == benchmark_symbol:
                continue
            sym_return = indicators.get("return_20d", 0.0)
            rs_scores[symbol] = sym_return - bench_return

        # Rank symbols by RS score
        sorted_symbols = sorted(rs_scores, key=lambda s: rs_scores[s], reverse=True)
        total = len(sorted_symbols) if sorted_symbols else 1

        for rank, symbol in enumerate(sorted_symbols):
            technicals[symbol]["rs_vs_spy"] = round(rs_scores[symbol], 4)
            technicals[symbol]["rs_rank_pct"] = round((1 - rank / total) * 100, 1)

        return technicals

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

        # Extended moving averages (Issue #22: multi-timeframe)
        if len(close) >= 100:
            indicators["sma_100"] = ta.trend.sma_indicator(close, window=100).iloc[-1]
        if len(close) >= 200:
            indicators["sma_200"] = ta.trend.sma_indicator(close, window=200).iloc[-1]
            indicators["price_vs_sma200"] = (close.iloc[-1] / indicators["sma_200"] - 1) * 100

        # Weekly trend proxy from daily data (Issue #22)
        if len(close) >= 60:
            weekly_close = close.iloc[-60:].iloc[::5]  # Sample last 60 bars, every 5th
            weekly_mean = weekly_close.rolling(window=10).mean().iloc[-1]
            if not math.isnan(weekly_mean):
                indicators["weekly_sma_10"] = weekly_mean
                indicators["weekly_trend"] = 1.0 if close.iloc[-1] > weekly_mean else -1.0

        # Momentum indicators
        indicators["rsi_14"] = ta.momentum.rsi(close, window=14).iloc[-1]
        stoch = ta.momentum.StochasticOscillator(high, low, close)
        indicators["stoch_k"] = stoch.stoch().iloc[-1]
        indicators["stoch_d"] = stoch.stoch_signal().iloc[-1]

        # ADX for trend strength (critical for momentum confirmation)
        if len(close) >= 14:
            adx_val = ta.trend.adx(high, low, close, window=14).iloc[-1]
            if not math.isnan(adx_val):
                indicators["adx_14"] = adx_val

        # Rate of Change for momentum velocity
        if len(close) >= 12:
            roc_val = ta.momentum.roc(close, window=12).iloc[-1]
            if not math.isnan(roc_val):
                indicators["roc_12"] = roc_val

        # Volatility indicators
        bb = ta.volatility.BollingerBands(close)
        indicators["bb_upper"] = bb.bollinger_hband().iloc[-1]
        indicators["bb_lower"] = bb.bollinger_lband().iloc[-1]
        indicators["bb_width"] = bb.bollinger_wband().iloc[-1]
        # Normalized BB width for cross-symbol comparison
        bb_mid = (indicators["bb_upper"] + indicators["bb_lower"]) / 2
        if bb_mid > 0:
            indicators["bb_width_pct"] = (indicators["bb_width"] / bb_mid) * 100
        indicators["atr_14"] = ta.volatility.average_true_range(high, low, close).iloc[-1]

        # ATR as % of price (Issue #28: volatility-aware sizing)
        current_price = close.iloc[-1]
        if current_price > 0:
            indicators["atr_pct"] = (indicators["atr_14"] / current_price) * 100

        # Volume indicators
        indicators["obv"] = ta.volume.on_balance_volume(close, volume).iloc[-1]
        avg_volume_20 = volume.rolling(window=20).mean().iloc[-1]
        indicators["avg_volume_20"] = avg_volume_20
        if avg_volume_20 > 0:
            indicators["relative_volume"] = volume.iloc[-1] / avg_volume_20

        # Support and resistance (Issue #25)
        indicators.update(self._support_resistance(high, low, close))

        # Current price context
        indicators["current_price"] = current_price
        indicators["price_vs_sma20"] = (close.iloc[-1] / indicators["sma_20"] - 1) * 100
        if len(close) >= 2:
            indicators["daily_return_pct"] = ((close.iloc[-1] / close.iloc[-2]) - 1) * 100
        else:
            indicators["daily_return_pct"] = 0.0

        # Multi-period returns for relative strength (Issue #29)
        if len(close) >= 20:
            indicators["return_20d"] = ((close.iloc[-1] / close.iloc[-20]) - 1) * 100
        if len(close) >= 60:
            indicators["return_60d"] = ((close.iloc[-1] / close.iloc[-60]) - 1) * 100

        # 52-week high/low (Issue #25)
        if len(close) >= 252:
            high_252 = high.iloc[-252:].max()
            low_252 = low.iloc[-252:].min()
        else:
            high_252 = high.max()
            low_252 = low.min()
        indicators["high_52w"] = high_252
        indicators["low_52w"] = low_252
        indicators["pct_from_52w_high"] = ((current_price / high_252) - 1) * 100
        indicators["pct_from_52w_low"] = ((current_price / low_252) - 1) * 100

        # Filter out NaN values to prevent downstream issues
        return {k: v for k, v in indicators.items() if not (isinstance(v, float) and math.isnan(v))}

    def _support_resistance(
        self,
        high: pd.Series[float],
        low: pd.Series[float],
        close: pd.Series[float],
    ) -> dict[str, float]:
        """Calculate support and resistance levels from swing highs/lows."""
        result: dict[str, float] = {}
        current = close.iloc[-1]

        # Recent swing highs and lows (last 60 bars, 5-bar pivots)
        window = min(len(close), 60)
        recent_high = high.iloc[-window:]
        recent_low = low.iloc[-window:]

        swing_highs: list[float] = []
        swing_lows: list[float] = []

        for i in range(2, len(recent_high) - 2):
            if (
                recent_high.iloc[i] > recent_high.iloc[i - 1]
                and recent_high.iloc[i] > recent_high.iloc[i - 2]
                and recent_high.iloc[i] > recent_high.iloc[i + 1]
                and recent_high.iloc[i] > recent_high.iloc[i + 2]
            ):
                swing_highs.append(float(recent_high.iloc[i]))

            if (
                recent_low.iloc[i] < recent_low.iloc[i - 1]
                and recent_low.iloc[i] < recent_low.iloc[i - 2]
                and recent_low.iloc[i] < recent_low.iloc[i + 1]
                and recent_low.iloc[i] < recent_low.iloc[i + 2]
            ):
                swing_lows.append(float(recent_low.iloc[i]))

        # Nearest resistance (closest swing high above current price)
        resistance_levels = sorted([h for h in swing_highs if h > current])
        if resistance_levels:
            result["nearest_resistance"] = resistance_levels[0]
            result["pct_to_resistance"] = ((resistance_levels[0] / current) - 1) * 100

        # Nearest support (closest swing low below current price)
        support_levels = sorted([s for s in swing_lows if s < current], reverse=True)
        if support_levels:
            result["nearest_support"] = support_levels[0]
            result["pct_to_support"] = ((support_levels[0] / current) - 1) * 100

        return result
