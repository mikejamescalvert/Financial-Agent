"""Fundamentals data provider using Financial Modeling Prep (FMP) stable API."""

from __future__ import annotations

import json
import time
import urllib.request
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from financial_agent.data.models import FundamentalData

log = structlog.get_logger()

_FMP_BASE = "https://financialmodelingprep.com/stable"


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
                data = self._fetch_fundamentals(symbol)
                if data is not None:
                    results[symbol] = data
            except Exception:
                log.warning("fundamentals_fetch_error", symbol=symbol, exc_info=True)

        log.info("fundamentals_fetched", count=len(results), total=len(symbols))
        return results

    def _fetch_json(self, endpoint: str, params: str = "") -> list[dict[str, object]]:
        """Fetch a JSON array from an FMP stable endpoint."""
        url = f"{_FMP_BASE}/{endpoint}?{params}&apikey={self._api_key}"
        req = urllib.request.Request(url)  # noqa: S310
        req.add_header("User-Agent", "FinancialAgent/1.0")

        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            body = json.loads(resp.read().decode())

        if not body or not isinstance(body, list) or len(body) == 0:
            return []
        return body  # type: ignore[no-any-return]

    def _fetch_fundamentals(self, symbol: str) -> FundamentalData | None:
        """Fetch a symbol's fundamentals from FMP stable endpoints.

        Combines data from three endpoints:
        - /stable/profile for market cap
        - /stable/ratios for financial ratios (P/E, margins, etc.)
        - /stable/financial-growth for revenue growth
        """
        from financial_agent.data.models import FundamentalData

        profile = self._fetch_json("profile", f"symbol={symbol}")
        if not profile:
            log.warning("fundamentals_empty_response", symbol=symbol)
            return None

        ratios = self._fetch_json("ratios", f"symbol={symbol}&period=annual&limit=1")
        growth = self._fetch_json("financial-growth", f"symbol={symbol}&period=annual&limit=1")

        p = profile[0]
        r = ratios[0] if ratios else {}
        g = growth[0] if growth else {}

        return FundamentalData(
            eps_ttm=_safe_float(r.get("netIncomePerShare")),
            pe_ratio=_safe_float(r.get("priceToEarningsRatio")),
            revenue_growth=_safe_float(g.get("revenueGrowth")),
            profit_margin=_safe_float(r.get("netProfitMargin")),
            debt_to_equity=_safe_float(r.get("debtToEquityRatio")),
            free_cash_flow=_safe_float(r.get("freeCashFlowPerShare")),
            price_to_book=_safe_float(r.get("priceToBookRatio")),
            market_cap=_safe_float(p.get("marketCap")),
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
