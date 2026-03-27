"""Fundamentals data provider using Financial Modeling Prep (FMP) stable API."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from financial_agent.data.models import FundamentalData

log = structlog.get_logger()

_FMP_BASE = "https://financialmodelingprep.com/stable"
_CACHE_FILE = ".data/fundamentals_cache.json"
_CACHE_MAX_AGE_HOURS = 12


class FundamentalsProvider:
    """Fetches fundamental financial data from FMP."""

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def fetch(self, symbols: list[str]) -> dict[str, FundamentalData]:
        """Fetch fundamental data for a list of symbols.

        Returns a dict mapping symbol -> FundamentalData. Symbols that fail
        to fetch are silently skipped (logged as warnings). Falls back to
        cached data when fresh fetches fail.
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
            except Exception as e:
                log.warning("fundamentals_fetch_error", symbol=symbol, error=str(e))

        # If we got results, cache them for offline use
        if results:
            self._save_cache(results)
            log.info("fundamentals_fetched", count=len(results), total=len(symbols))
            return results

        # No fresh data — try the cache
        cached = self._load_cache(symbols)
        if cached:
            log.info(
                "fundamentals_fetched_from_cache",
                count=len(cached),
                total=len(symbols),
            )
            return cached

        log.info("fundamentals_fetched", count=0, total=len(symbols))
        return results

    def _save_cache(self, results: dict[str, FundamentalData]) -> None:
        """Persist fundamentals to disk for offline fallback."""
        try:
            cache_path = Path(_CACHE_FILE)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_data = {
                "timestamp": datetime.now(tz=UTC).isoformat(),
                "data": {
                    sym: {
                        "eps_ttm": fd.eps_ttm,
                        "pe_ratio": fd.pe_ratio,
                        "revenue_growth": fd.revenue_growth,
                        "profit_margin": fd.profit_margin,
                        "debt_to_equity": fd.debt_to_equity,
                        "free_cash_flow": fd.free_cash_flow,
                        "price_to_book": fd.price_to_book,
                        "market_cap": fd.market_cap,
                    }
                    for sym, fd in results.items()
                },
            }
            cache_path.write_text(json.dumps(cache_data))
        except Exception:
            log.debug("fundamentals_cache_save_failed", exc_info=True)

    def _load_cache(self, symbols: list[str]) -> dict[str, FundamentalData]:
        """Load cached fundamentals if fresh enough."""
        from financial_agent.data.models import FundamentalData

        try:
            cache_path = Path(_CACHE_FILE)
            if not cache_path.exists():
                return {}

            raw = json.loads(cache_path.read_text())
            cached_time = datetime.fromisoformat(raw["timestamp"])
            if cached_time.tzinfo is None:
                cached_time = cached_time.replace(tzinfo=UTC)
            age_hours = (datetime.now(tz=UTC) - cached_time).total_seconds() / 3600

            if age_hours > _CACHE_MAX_AGE_HOURS:
                log.debug("fundamentals_cache_expired", age_hours=round(age_hours, 1))
                return {}

            results: dict[str, FundamentalData] = {}
            symbol_set = {s.upper() for s in symbols}
            for sym, vals in raw.get("data", {}).items():
                if sym.upper() in symbol_set:
                    results[sym] = FundamentalData(**vals)
            return results
        except Exception:
            log.debug("fundamentals_cache_load_failed", exc_info=True)
            return {}

    def _fetch_json(self, endpoint: str, params: str = "") -> list[dict[str, object]]:
        """Fetch JSON from an FMP stable endpoint. Handles both dict and list responses."""
        url = f"{_FMP_BASE}/{endpoint}?{params}&apikey={self._api_key}"
        req = urllib.request.Request(url)  # noqa: S310
        req.add_header("User-Agent", "FinancialAgent/1.0")

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            log.warning(
                "fmp_http_error",
                endpoint=endpoint,
                status=e.code,
                error=error_body[:200],
            )
            raise

        if not body:
            return []
        # FMP error responses: {"Error Message": "..."} or {"message": "..."}
        if isinstance(body, dict):
            if "Error Message" in body or "error" in body:
                msg = body.get("Error Message") or body.get("error") or body.get("message", "")
                log.warning("fmp_api_error", endpoint=endpoint, error=str(msg))
                return []
            return [body]
        if not isinstance(body, list):
            return []
        return body

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
