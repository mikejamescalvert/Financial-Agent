"""Macro-economic context provider using free public data sources."""

from __future__ import annotations

import json
import urllib.request
from datetime import date

import structlog

from financial_agent.data.models import MacroContext

log = structlog.get_logger()

_YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart"

# Hardcoded economic calendar events by month for 2026.
_UPCOMING_EVENTS_2026: dict[int, list[str]] = {
    1: ["FOMC Meeting Jan 27-28", "CPI Release Jan 14", "Jobs Report Jan 9"],
    2: ["CPI Release Feb 12", "Jobs Report Feb 6", "Retail Sales Feb 14"],
    3: ["FOMC Meeting Mar 17-18", "CPI Release Mar 11", "Jobs Report Mar 6"],
    4: ["CPI Release Apr 10", "Jobs Report Apr 3", "Retail Sales Apr 15"],
    5: ["FOMC Meeting May 5-6", "CPI Release May 13", "Jobs Report May 8"],
    6: ["FOMC Meeting Jun 16-17", "CPI Release Jun 10", "Jobs Report Jun 5"],
    7: ["CPI Release Jul 14", "Jobs Report Jul 2", "Retail Sales Jul 16"],
    8: ["FOMC Meeting Aug 4-5", "CPI Release Aug 12", "Jobs Report Aug 7"],
    9: ["FOMC Meeting Sep 15-16", "CPI Release Sep 10", "Jobs Report Sep 4"],
    10: ["CPI Release Oct 13", "Jobs Report Oct 2", "Retail Sales Oct 16"],
    11: ["FOMC Meeting Nov 3-4", "CPI Release Nov 12", "Jobs Report Nov 6"],
    12: ["FOMC Meeting Dec 15-16", "CPI Release Dec 10", "Jobs Report Dec 4"],
}


class MacroProvider:
    """Fetches macro-economic context from free public APIs."""

    def __init__(self) -> None:
        pass

    def fetch(self) -> MacroContext:
        """Fetch macro context including VIX, SPY trend, and upcoming events.

        Returns a MacroContext with None values on any failure.
        """
        try:
            return self._build_context()
        except Exception:
            log.warning("macro_fetch_error", exc_info=True)
            return MacroContext()

    def _build_context(self) -> MacroContext:
        """Build the full macro context from multiple data sources."""
        vix_level, vix_trend = self._fetch_vix()
        spy_trend = self._fetch_spy_trend()
        regime = _determine_regime(vix_level)
        events = _get_upcoming_events()

        return MacroContext(
            vix_level=vix_level,
            vix_trend=vix_trend,
            spy_trend=spy_trend,
            ten_year_yield=None,
            market_regime=regime,
            upcoming_events=events,
        )

    def _fetch_vix(self) -> tuple[float | None, str]:
        """Fetch VIX level and trend from Yahoo Finance."""
        try:
            data = _yahoo_chart("%5EVIX", "5d", "1d")
            closes = _extract_closes(data)

            if not closes:
                return None, "stable"

            current = closes[-1]
            trend = "stable"

            if len(closes) >= 2:
                prev = closes[-2]
                if current > prev * 1.05:
                    trend = "rising"
                elif current < prev * 0.95:
                    trend = "falling"

            return current, trend
        except Exception:
            log.warning("vix_fetch_error", exc_info=True)
            return None, "stable"

    def _fetch_spy_trend(self) -> str:
        """Determine SPY trend relative to its recent moving average."""
        try:
            data = _yahoo_chart("SPY", "1mo", "1d")
            closes = _extract_closes(data)

            if not closes or len(closes) < 5:
                return "neutral"

            current = closes[-1]
            sma = sum(closes) / len(closes)

            if current > sma * 1.01:
                return "bullish"
            elif current < sma * 0.99:
                return "bearish"
            else:
                return "neutral"
        except Exception:
            log.warning("spy_trend_error", exc_info=True)
            return "neutral"


def _yahoo_chart(symbol: str, range_: str, interval: str) -> dict[str, object]:
    """Fetch chart data from Yahoo Finance."""
    url = f"{_YAHOO_CHART}/{symbol}?range={range_}&interval={interval}"
    req = urllib.request.Request(url)  # noqa: S310
    req.add_header("User-Agent", "Mozilla/5.0 (FinancialAgent/1.0)")

    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read().decode())  # type: ignore[no-any-return]


def _extract_closes(data: dict[str, object]) -> list[float]:
    """Extract close prices from Yahoo Finance chart response."""
    try:
        chart = data.get("chart", {})
        if not isinstance(chart, dict):
            return []

        result_list = chart.get("result", [])
        if not isinstance(result_list, list) or not result_list:
            return []

        result = result_list[0]
        if not isinstance(result, dict):
            return []

        indicators = result.get("indicators", {})
        if not isinstance(indicators, dict):
            return []

        quote_list = indicators.get("quote", [])
        if not isinstance(quote_list, list) or not quote_list:
            return []

        quote = quote_list[0]
        if not isinstance(quote, dict):
            return []

        closes_raw = quote.get("close", [])
        if not isinstance(closes_raw, list):
            return []

        return [float(c) for c in closes_raw if c is not None]
    except (KeyError, IndexError, TypeError, ValueError):
        return []


def _determine_regime(vix_level: float | None) -> str:
    """Determine market regime from VIX level."""
    if vix_level is None:
        return "neutral"
    if vix_level > 30.0:
        return "risk_off"
    if vix_level < 15.0:
        return "risk_on"
    return "neutral"


def _get_upcoming_events() -> list[str]:
    """Return hardcoded upcoming economic events for the current month."""
    current_month = date.today().month
    return _UPCOMING_EVENTS_2026.get(current_month, [])
