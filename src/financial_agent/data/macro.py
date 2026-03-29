"""Macro-economic context provider using free public data sources."""

from __future__ import annotations

import json
import urllib.request
from datetime import date

import structlog

from financial_agent.data.models import MacroContext

log = structlog.get_logger()

_YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart"

# FOMC meetings are held ~8 times/year on a fixed schedule.
# CPI is released around the 10th-14th of each month.
# Jobs Report (NFP) is the first Friday of each month.
# These approximate patterns hold year over year.
_RECURRING_EVENTS: list[str] = [
    "FOMC Meeting (check federalreserve.gov for exact dates)",
    "CPI Release (~10th-14th of month)",
    "Jobs Report (1st Friday of month)",
]


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
        ten_year_yield = self._fetch_ten_year_yield()
        regime = _determine_regime(vix_level)
        events = _get_upcoming_events()

        return MacroContext(
            vix_level=vix_level,
            vix_trend=vix_trend,
            spy_trend=spy_trend,
            ten_year_yield=ten_year_yield,
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

    def _fetch_ten_year_yield(self) -> float | None:
        """Fetch the 10-year Treasury yield from Yahoo Finance."""
        try:
            data = _yahoo_chart("%5ETNX", "5d", "1d")
            closes = _extract_closes(data)
            if closes:
                return round(closes[-1], 2)
        except Exception:
            log.debug("ten_year_yield_fetch_failed", exc_info=True)
        return None

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
    """Return approximate upcoming economic events.

    Uses recurring patterns rather than hardcoded dates, so it works
    across years without manual updates.
    """
    today = date.today()
    events: list[str] = []

    # Jobs report: first Friday of the month
    first_day = today.replace(day=1)
    # Monday=0 ... Friday=4; days until first Friday
    days_to_friday = (4 - first_day.weekday()) % 7
    first_friday = first_day.replace(day=1 + days_to_friday)
    if first_friday >= today:
        events.append(f"Jobs Report {first_friday.strftime('%b %d')}")

    # CPI: typically around the 10th-14th
    cpi_approx = today.replace(day=12)
    if cpi_approx >= today:
        events.append(f"CPI Release ~{cpi_approx.strftime('%b %d')}")

    # Generic FOMC reminder (meets ~8x/year, roughly every 6 weeks)
    events.append("FOMC (check schedule)")

    return events
