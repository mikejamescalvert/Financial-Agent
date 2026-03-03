"""Earnings calendar provider using Financial Modeling Prep (FMP) free API."""

from __future__ import annotations

import json
import urllib.request
from datetime import date, timedelta
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from financial_agent.data.models import EarningsEvent

log = structlog.get_logger()

_FMP_BASE = "https://financialmodelingprep.com/stable"


class EarningsProvider:
    """Fetches upcoming earnings events from FMP."""

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def fetch(self, symbols: list[str]) -> list[EarningsEvent]:
        """Fetch upcoming earnings events for the given symbols.

        Returns events within the next 14 days, sorted by days until earnings.
        """
        if not self._api_key:
            log.info("earnings_skip", reason="no FMP API key configured")
            return []

        try:
            return self._fetch_calendar(symbols)
        except Exception:
            log.warning("earnings_fetch_error", exc_info=True)
            return []

    def _fetch_calendar(self, symbols: list[str]) -> list[EarningsEvent]:
        """Fetch the earnings calendar and filter to target symbols."""
        from financial_agent.data.models import EarningsEvent

        today = date.today()
        from_date = today.isoformat()
        to_date = (today + timedelta(days=14)).isoformat()

        url = f"{_FMP_BASE}/earnings-calendar?from={from_date}&to={to_date}&apikey={self._api_key}"
        req = urllib.request.Request(url)  # noqa: S310
        req.add_header("User-Agent", "FinancialAgent/1.0")

        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            body = json.loads(resp.read().decode())

        # Handle dict response (FMP stable API may return a single object)
        if isinstance(body, dict):
            body = [body]
        if not isinstance(body, list):
            log.warning("earnings_unexpected_response", body_type=type(body).__name__)
            return []

        symbol_set = {s.upper() for s in symbols}
        events: list[EarningsEvent] = []

        for item in body:
            sym = str(item.get("symbol", "")).upper()
            if sym not in symbol_set:
                continue

            earnings_date_str = item.get("date")
            if not earnings_date_str:
                continue

            try:
                earnings_date = date.fromisoformat(earnings_date_str)
            except ValueError:
                log.warning("earnings_bad_date", symbol=sym, date_str=earnings_date_str)
                continue

            days_until = (earnings_date - today).days

            events.append(
                EarningsEvent(
                    symbol=sym,
                    earnings_date=earnings_date,
                    days_until_earnings=days_until,
                    eps_estimate=_safe_float(item.get("epsEstimated")),
                )
            )

        events.sort(key=lambda e: e.days_until_earnings)
        log.info("earnings_fetched", count=len(events), symbols_checked=len(symbols))
        return events


def _safe_float(value: object) -> float | None:
    """Safely convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    else:
        return result
