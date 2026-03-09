"""Crypto market context provider using free public APIs."""

from __future__ import annotations

import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import structlog

from financial_agent.data.models import CryptoMarketContext

log = structlog.get_logger()

_COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"
# Primary and fallback Fear & Greed endpoints
_FEAR_GREED_URLS = [
    "https://api.alternative.me/fng/?limit=1",
    "https://api.alternative.me/fapi/v1/fear-and-greed-index/",
]

_FEAR_GREED_LABELS: dict[str, str] = {
    "Extreme Fear": "extreme_fear",
    "Fear": "fear",
    "Neutral": "neutral",
    "Greed": "greed",
    "Extreme Greed": "extreme_greed",
}

_CACHE_FILE = ".data/crypto_market_cache.json"
_CACHE_MAX_AGE_HOURS = 4


class CryptoMarketProvider:
    """Fetches crypto market structure data from free public APIs."""

    def __init__(self) -> None:
        pass

    def fetch(self) -> CryptoMarketContext:
        """Fetch crypto market context.

        Returns a CryptoMarketContext with None values on any failure.
        Falls back to cached data when APIs are unavailable.
        """
        try:
            ctx = self._build_context()
            # Cache if we got meaningful data
            if ctx.btc_dominance is not None or ctx.fear_greed_index is not None:
                self._save_cache(ctx)
            return ctx
        except Exception:
            log.warning("crypto_market_fetch_error", exc_info=True)
            cached = self._load_cache()
            if cached:
                return cached
            return CryptoMarketContext()

    def _build_context(self) -> CryptoMarketContext:
        """Build the full crypto market context from multiple sources."""
        btc_dominance, total_market_cap, btc_trend = self._fetch_global()
        fear_greed_index, fear_greed_label = self._fetch_fear_greed()

        return CryptoMarketContext(
            btc_dominance=btc_dominance,
            fear_greed_index=fear_greed_index,
            fear_greed_label=fear_greed_label,
            btc_trend=btc_trend,
            total_market_cap=total_market_cap,
        )

    def _fetch_global(self) -> tuple[float | None, float | None, str]:
        """Fetch global crypto data from CoinGecko.

        Returns (btc_dominance, total_market_cap, btc_trend).
        """
        try:
            data = _fetch_json(_COINGECKO_GLOBAL)

            global_data = data.get("data", {})
            if not isinstance(global_data, dict):
                return None, None, "neutral"

            # BTC dominance
            market_cap_pct = global_data.get("market_cap_percentage", {})
            btc_dominance: float | None = None
            if isinstance(market_cap_pct, dict):
                raw_btc = market_cap_pct.get("btc")
                if raw_btc is not None:
                    btc_dominance = round(float(raw_btc), 2)

            # Total market cap (USD)
            total_cap: float | None = None
            total_market_cap_raw = global_data.get("total_market_cap", {})
            if isinstance(total_market_cap_raw, dict):
                usd_cap = total_market_cap_raw.get("usd")
                if usd_cap is not None:
                    total_cap = float(usd_cap)

            # BTC trend from 24h market cap change
            btc_trend = "neutral"
            change_raw = global_data.get("market_cap_change_percentage_24h_usd")
            if change_raw is not None:
                change = float(change_raw)
                if change > 1.0:
                    btc_trend = "bullish"
                elif change < -1.0:
                    btc_trend = "bearish"

            return btc_dominance, total_cap, btc_trend
        except Exception:
            log.warning("coingecko_fetch_error", exc_info=True)
            return None, None, "neutral"

    def _fetch_fear_greed(self) -> tuple[int | None, str]:
        """Fetch the crypto Fear & Greed Index.

        Tries multiple endpoint URLs as fallback. Returns (index_value, label).
        """
        for url in _FEAR_GREED_URLS:
            try:
                data = _fetch_json(url)

                data_list = data.get("data", [])
                if not isinstance(data_list, list) or not data_list:
                    continue

                entry = data_list[0]
                if not isinstance(entry, dict):
                    continue

                value = int(entry.get("value", 0))
                raw_label = str(entry.get("value_classification", "Neutral"))
                label = _FEAR_GREED_LABELS.get(raw_label, "neutral")

                return value, label
            except Exception:
                log.debug("fear_greed_endpoint_failed", url=url, exc_info=True)

        log.warning("fear_greed_fetch_error", reason="all endpoints failed")
        return None, "neutral"

    def _save_cache(self, ctx: CryptoMarketContext) -> None:
        """Persist crypto market data to disk for offline fallback."""
        try:
            cache_path = Path(_CACHE_FILE)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_data = {
                "timestamp": datetime.now(tz=UTC).isoformat(),
                "btc_dominance": ctx.btc_dominance,
                "fear_greed_index": ctx.fear_greed_index,
                "fear_greed_label": ctx.fear_greed_label,
                "btc_trend": ctx.btc_trend,
                "total_market_cap": ctx.total_market_cap,
            }
            cache_path.write_text(json.dumps(cache_data))
        except Exception:
            log.debug("crypto_cache_save_failed", exc_info=True)

    def _load_cache(self) -> CryptoMarketContext | None:
        """Load cached crypto market data if fresh enough."""
        try:
            cache_path = Path(_CACHE_FILE)
            if not cache_path.exists():
                return None

            raw = json.loads(cache_path.read_text())
            cached_time = datetime.fromisoformat(raw["timestamp"])
            age_hours = (datetime.now(tz=UTC) - cached_time).total_seconds() / 3600

            if age_hours > _CACHE_MAX_AGE_HOURS:
                return None

            log.info("crypto_market_loaded_from_cache", age_hours=round(age_hours, 1))
            return CryptoMarketContext(
                btc_dominance=raw.get("btc_dominance"),
                fear_greed_index=raw.get("fear_greed_index"),
                fear_greed_label=raw.get("fear_greed_label", "neutral"),
                btc_trend=raw.get("btc_trend", "neutral"),
                total_market_cap=raw.get("total_market_cap"),
            )
        except Exception:
            log.debug("crypto_cache_load_failed", exc_info=True)
            return None


def _fetch_json(url: str) -> dict[str, object]:
    """Fetch JSON data from a URL."""
    req = urllib.request.Request(url)  # noqa: S310
    req.add_header("User-Agent", "FinancialAgent/1.0")

    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read().decode())  # type: ignore[no-any-return]
