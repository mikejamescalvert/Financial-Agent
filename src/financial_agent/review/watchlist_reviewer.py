"""Watchlist reviewer that screens a broad universe and selects optimal targets."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import anthropic
import structlog

if TYPE_CHECKING:
    from financial_agent.config import AIConfig, TradingConfig
    from financial_agent.portfolio.models import PortfolioSnapshot

log = structlog.get_logger()

WATCHLIST_SYSTEM_PROMPT = """\
You are an expert quantitative analyst responsible for curating a trading bot's watchlist. \
Your job is to review technical indicators across a broad screening universe and select the \
best symbols for active monitoring and trading.

Goals:
1. **Select the strongest candidates** — symbols with the best risk/reward setup based on \
   technical indicators (momentum, trend, volatility, volume).
2. **Maintain diversification** — spread across sectors and avoid clustering in correlated names.
3. **Drop underperformers** — remove symbols with deteriorating technicals or no clear setup.
4. **Right-size the list** — stocks: 8-12 symbols, crypto: 3-5 symbols. Too many dilutes focus.

Evaluation criteria per symbol:
- Trend: SMA alignment (20 > 50 = bullish), MACD histogram direction
- Momentum: RSI between 40-70 (not overbought/oversold), positive stochastic crossover
- Volatility: Reasonable ATR, Bollinger Band width (not too compressed or expanded)
- Volume: OBV trending up, VWAP supportive
- Price action: Trading above key moving averages, positive daily returns

Rules:
- Keep any symbol the bot currently holds a position in (you can flag it for review but \
  don't remove it from the watchlist).
- Prefer liquid, well-known names over obscure tickers.
- For crypto, strongly prefer BTC and ETH as core holdings; limit altcoins.
- Consider the current strategy mode when selecting (conservative = blue chips, \
  momentum = growth/tech).
- Explain WHY each symbol was added or removed.

Respond ONLY with valid JSON matching this schema:
{
  "summary": "2-3 sentence overview of market conditions and watchlist changes",
  "stock_watchlist": ["AAPL", "MSFT", ...],
  "crypto_watchlist": ["BTC/USD", "ETH/USD", ...],
  "changes": [
    {
      "symbol": "AAPL",
      "action": "add|remove|keep",
      "reason": "Explanation of why this symbol was added, removed, or kept"
    }
  ]
}
"""


class WatchlistReviewer:
    """Screens a broad universe and selects optimal watchlist targets."""

    def __init__(self, ai_config: AIConfig, trading_config: TradingConfig) -> None:
        self._client = anthropic.Anthropic(api_key=ai_config.api_key)
        self._model = ai_config.model
        self._max_tokens = ai_config.max_tokens
        self._trading_config = trading_config

    def review(
        self,
        portfolio: PortfolioSnapshot,
        technicals: dict[str, dict[str, float]],
    ) -> dict[str, Any]:
        """Analyze the screening universe and return updated watchlists.

        Returns a dict with keys: summary, stock_watchlist, crypto_watchlist, changes.
        """
        prompt = self._build_prompt(portfolio, technicals)

        log.info(
            "watchlist_review_started",
            model=self._model,
            universe_size=len(technicals),
        )

        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=WATCHLIST_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw_text = response.content[0].text  # type: ignore[union-attr]
        result = self._parse_response(raw_text)

        log.info(
            "watchlist_review_complete",
            stocks=len(result.get("stock_watchlist", [])),
            crypto=len(result.get("crypto_watchlist", [])),
            changes=len(result.get("changes", [])),
        )

        return result

    def _build_prompt(
        self,
        portfolio: PortfolioSnapshot,
        technicals: dict[str, dict[str, float]],
    ) -> str:
        """Build the screening prompt with universe data."""
        current_stocks = [s.strip() for s in self._trading_config.watchlist.split(",")]
        current_crypto = [s.strip() for s in self._trading_config.crypto_watchlist.split(",")]

        held_symbols = [p.symbol for p in portfolio.positions]

        # Separate stock and crypto technicals
        stock_technicals = {k: v for k, v in technicals.items() if "/" not in k}
        crypto_technicals = {k: v for k, v in technicals.items() if "/" in k}

        return f"""## Watchlist Review Request

## Current Strategy: {self._trading_config.strategy}

## Current Stock Watchlist
{json.dumps(current_stocks, indent=2)}

## Current Crypto Watchlist
{json.dumps(current_crypto, indent=2)}

## Currently Held Positions (DO NOT remove these from watchlist)
{json.dumps(held_symbols, indent=2)}

## Portfolio Context
- Equity: ${portfolio.equity:,.2f}
- Cash: ${portfolio.cash:,.2f}
- Positions: {portfolio.position_count}

## Stock Universe Technical Indicators
{
            json.dumps(
                {
                    k: {ik: round(iv, 4) for ik, iv in v.items()}
                    for k, v in stock_technicals.items()
                },
                indent=2,
            )
        }

## Crypto Universe Technical Indicators
{
            json.dumps(
                {
                    k: {ik: round(iv, 4) for ik, iv in v.items()}
                    for k, v in crypto_technicals.items()
                },
                indent=2,
            )
        }

Review the technical data for the full screening universe. Select the best 8-12 stocks \
and 3-5 crypto symbols for the active watchlist. Explain each add/remove decision.
"""

    def _parse_response(self, raw: str) -> dict[str, Any]:
        """Parse Claude's JSON response into watchlist recommendations."""
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        try:
            data: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError:
            log.error("watchlist_review_parse_error", raw=raw[:500])
            return {
                "summary": "Failed to parse AI watchlist review.",
                "stock_watchlist": [],
                "crypto_watchlist": [],
                "changes": [],
            }

        return data
