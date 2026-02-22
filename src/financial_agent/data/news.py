"""News sentiment provider using Finnhub free API."""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import date, timedelta
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from financial_agent.data.models import NewsItem, NewsSentiment

log = structlog.get_logger()

_FINNHUB_BASE = "https://finnhub.io/api/v1"

_POSITIVE_WORDS: frozenset[str] = frozenset(
    {"surge", "beat", "upgrade", "growth", "profit", "record", "breakout"}
)
_NEGATIVE_WORDS: frozenset[str] = frozenset(
    {"miss", "downgrade", "decline", "loss", "cut", "warning", "crash"}
)

_MAX_SYMBOLS = 5


class NewsProvider:
    """Fetches company news and computes simple headline sentiment."""

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def fetch(self, symbols: list[str]) -> dict[str, NewsSentiment]:
        """Fetch news sentiment for up to 5 symbols.

        Returns a dict mapping symbol -> NewsSentiment.
        """
        if not self._api_key:
            log.info("news_skip", reason="no Finnhub API key configured")
            return {}

        results: dict[str, NewsSentiment] = {}
        capped = symbols[:_MAX_SYMBOLS]

        for i, symbol in enumerate(capped):
            if i > 0:
                time.sleep(1.0)

            try:
                sentiment = self._fetch_symbol_news(symbol)
                if sentiment is not None:
                    results[symbol] = sentiment
            except Exception:
                log.warning("news_fetch_error", symbol=symbol, exc_info=True)

        log.info("news_fetched", count=len(results), total=len(capped))
        return results

    def _fetch_symbol_news(self, symbol: str) -> NewsSentiment | None:
        """Fetch news articles for a single symbol and compute sentiment."""
        from financial_agent.data.models import NewsItem, NewsSentiment

        today = date.today()
        week_ago = (today - timedelta(days=7)).isoformat()
        today_str = today.isoformat()

        url = (
            f"{_FINNHUB_BASE}/company-news"
            f"?symbol={symbol}&from={week_ago}&to={today_str}&token={self._api_key}"
        )
        req = urllib.request.Request(url)  # noqa: S310
        req.add_header("User-Agent", "FinancialAgent/1.0")

        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            body = json.loads(resp.read().decode())

        if not isinstance(body, list):
            log.warning("news_unexpected_response", symbol=symbol)
            return None

        items: list[NewsItem] = []
        for article in body:
            headline = str(article.get("headline", ""))
            if not headline:
                continue

            score = _compute_headline_sentiment(headline)
            items.append(
                NewsItem(
                    headline=headline,
                    sentiment_score=score,
                    source=str(article.get("source", "")),
                    published_at=str(article.get("datetime", "")),
                )
            )

        if not items:
            return NewsSentiment(symbol=symbol)

        avg = sum(it.sentiment_score for it in items) / len(items)

        return NewsSentiment(
            symbol=symbol,
            items=items,
            avg_sentiment=round(avg, 4),
            headline_count=len(items),
        )


def _compute_headline_sentiment(headline: str) -> float:
    """Compute a simple keyword-based sentiment score for a headline.

    Returns a float in [-1.0, 1.0].
    """
    words = headline.lower().split()
    score = 0.0

    for word in words:
        # Strip punctuation for matching
        cleaned = word.strip(".,!?;:'\"()-")
        if cleaned in _POSITIVE_WORDS:
            score += 0.3
        elif cleaned in _NEGATIVE_WORDS:
            score -= 0.3

    return max(-1.0, min(1.0, score))
