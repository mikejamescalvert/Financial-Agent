"""Fundamentals data provider using Financial Modeling Prep (FMP) free API."""

from __future__ import annotations

import json
import time
import urllib.request
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from financial_agent.data.models import FundamentalData

log = structlog.get_logger()

_FMP_BASE = "https://financialmodelingprep.com/api/v3"


class FundamentalsProvider:
    """Fetches fundamental financial data from FMP."""

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def fetch(self, symbols: list[str]) -> dict[str, FundamentalData]:
        """Fetch fundamental data for a list of symbols.

        Returns a dict mapping symbol -> FundamentalData. Symbols that fail
        to fetch are silently skipped (logged as warnings).
        """
        if not self._api_key:
            log.info("fundamentals_skip", reason="no FMP API key configured")
            return {}

        results: dict[str, FundamentalData] = {}

        for i, symbol in enumerate(symbols):
            if i > 0:
                time.sleep(0.5)

            try:
                data = self._fetch_profile(symbol)
                if data is not None:
                    results[symbol] = data
            except Exception:
                log.warning("fundamentals_fetch_error", symbol=symbol, exc_info=True)

        log.info("fundamentals_fetched", count=len(results), total=len(symbols))
        return results

    def _fetch_profile(self, symbol: str) -> FundamentalData | None:
        """Fetch a single symbol's profile from FMP and parse into model."""
        from financial_agent.data.models import FundamentalData

        url = f"{_FMP_BASE}/profile/{symbol}?apikey={self._api_key}"
        req = urllib.request.Request(url)  # noqa: S310
        req.add_header("User-Agent", "FinancialAgent/1.0")

        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            body = json.loads(resp.read().decode())

        if not body or not isinstance(body, list) or len(body) == 0:
            log.warning("fundamentals_empty_response", symbol=symbol)
            return None

        profile = body[0]

        return FundamentalData(
            eps_ttm=_safe_float(profile.get("eps")),
            pe_ratio=_safe_float(profile.get("pe")),
            revenue_growth=_safe_float(profile.get("revenueGrowth")),
            profit_margin=_safe_float(profile.get("netIncomeMargin")),
            debt_to_equity=_safe_float(profile.get("debtToEquity")),
            free_cash_flow=_safe_float(profile.get("freeCashFlow")),
            price_to_book=_safe_float(profile.get("priceToBook")),
            market_cap=_safe_float(profile.get("mktCap")),
        )


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
