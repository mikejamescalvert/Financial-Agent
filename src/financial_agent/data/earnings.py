"""Earnings calendar provider using Financial Modeling Prep (FMP) stable API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from financial_agent.data.models import EarningsEvent

log = structlog.get_logger()

_FMP_BASE = "https://financialmodelingprep.com/stable"
_CACHE_FILE = ".data/earnings_cache.json"
_CACHE_MAX_AGE_HOURS = 12


class EarningsProvider:
    """Fetches upcoming earnings events from FMP."""

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def fetch(self, symbols: list[str]) -> list[EarningsEvent]:
        """Fetch upcoming earnings events for the given symbols.

        Returns events within the next 14 days, sorted by days until earnings.
        Falls back to cached data when the API is unavailable.
        """
        if not self._api_key:
            log.info("earnings_skip", reason="no FMP API key configured")
            return []

        try:
            result = self._fetch_calendar(symbols)
            if result is not None:
                self._save_cache(result, symbols)
            return result if result is not None else self._load_cache(symbols)
        except Exception as e:
            log.warning("earnings_fetch_error", error=str(e))
            return self._load_cache(symbols)

    def _save_cache(self, events: list[EarningsEvent], symbols: list[str]) -> None:
        """Persist earnings data to disk for offline fallback."""
        try:
            cache_path = Path(_CACHE_FILE)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_data = {
                "timestamp": datetime.now(tz=UTC).isoformat(),
                "symbols": symbols,
                "events": [
                    {
                        "symbol": e.symbol,
                        "earnings_date": e.earnings_date.isoformat(),
                        "days_until_earnings": e.days_until_earnings,
                        "eps_estimate": e.eps_estimate,
                    }
                    for e in events
                ],
            }
            cache_path.write_text(json.dumps(cache_data))
        except Exception:
            log.debug("earnings_cache_save_failed", exc_info=True)

    def _load_cache(self, symbols: list[str]) -> list[EarningsEvent]:
        """Load cached earnings if fresh enough."""
        from financial_agent.data.models import EarningsEvent

        try:
            cache_path = Path(_CACHE_FILE)
            if not cache_path.exists():
                return []

            raw = json.loads(cache_path.read_text())
            cached_time = datetime.fromisoformat(raw["timestamp"])
            age_hours = (datetime.now(tz=UTC) - cached_time).total_seconds() / 3600

            if age_hours > _CACHE_MAX_AGE_HOURS:
                return []

            symbol_set = {s.upper() for s in symbols}
            today = date.today()
            events: list[EarningsEvent] = []
            for e in raw.get("events", []):
                if e["symbol"].upper() not in symbol_set:
                    continue
                earnings_date = date.fromisoformat(e["earnings_date"])
                days_until = (earnings_date - today).days
                if days_until < 0:
                    continue
                events.append(
                    EarningsEvent(
                        symbol=e["symbol"],
                        earnings_date=earnings_date,
                        days_until_earnings=days_until,
                        eps_estimate=e.get("eps_estimate"),
                    )
                )
            events.sort(key=lambda ev: ev.days_until_earnings)
            if events:
                log.info("earnings_loaded_from_cache", count=len(events))
            return events
        except Exception:
            log.debug("earnings_cache_load_failed", exc_info=True)
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
