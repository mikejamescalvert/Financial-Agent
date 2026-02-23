"""Crypto market context provider using free public APIs."""

from __future__ import annotations

import json
import urllib.request

import structlog

from financial_agent.data.models import CryptoMarketContext

log = structlog.get_logger()

_COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"
_FEAR_GREED_URL = "https://api.alternative.me/fapi/v1/fear-and-greed-index/"

_FEAR_GREED_LABELS: dict[str, str] = {
    "Extreme Fear": "extreme_fear",
    "Fear": "fear",
    "Neutral": "neutral",
    "Greed": "greed",
    "Extreme Greed": "extreme_greed",
}


class CryptoMarketProvider:
    """Fetches crypto market structure data from free public APIs."""

    def __init__(self) -> None:
        pass

    def fetch(self) -> CryptoMarketContext:
        """Fetch crypto market context.

        Returns a CryptoMarketContext with None values on any failure.
        """
        try:
            return self._build_context()
        except Exception:
            log.warning("crypto_market_fetch_error", exc_info=True)
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

        Returns (index_value, label).
        """
        try:
            data = _fetch_json(_FEAR_GREED_URL)

            data_list = data.get("data", [])
            if not isinstance(data_list, list) or not data_list:
                return None, "neutral"

            entry = data_list[0]
            if not isinstance(entry, dict):
                return None, "neutral"

            value = int(entry.get("value", 0))
            raw_label = str(entry.get("value_classification", "Neutral"))
            label = _FEAR_GREED_LABELS.get(raw_label, "neutral")

            return value, label
        except Exception:
            log.warning("fear_greed_fetch_error", exc_info=True)
            return None, "neutral"


def _fetch_json(url: str) -> dict[str, object]:
    """Fetch JSON data from a URL."""
    req = urllib.request.Request(url)  # noqa: S310
    req.add_header("User-Agent", "FinancialAgent/1.0")

    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        return json.loads(resp.read().decode())  # type: ignore[no-any-return]
