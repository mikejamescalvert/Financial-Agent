"""Portfolio reviewer that analyzes performance and generates GitHub issue suggestions."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import anthropic
import structlog

if TYPE_CHECKING:
    from financial_agent.config import AIConfig, TradingConfig
    from financial_agent.portfolio.models import PortfolioSnapshot

log = structlog.get_logger()

REVIEW_SYSTEM_PROMPT = """\
You are an expert portfolio manager and quantitative analyst reviewing a trading bot's \
performance. Your job is to analyze the portfolio's current state, identify problems, and \
suggest concrete improvements to the trading strategy and code.

Focus on:
1. **Performance issues** — positions with large unrealized losses, poor risk/reward.
2. **Concentration risk** — over-allocation to single positions or correlated assets.
3. **Strategy gaps** — missed opportunities, incorrect position sizing, parameter tuning.
4. **Code suggestions** — concrete changes to config values, strategy logic, or watchlist \
   that would improve results.

Rules:
- Be specific and actionable. Reference exact symbols, percentages, and config parameters.
- Prioritize suggestions by expected impact (high/medium/low).
- Limit to 3-5 suggestions to keep issues focused.
- Each suggestion should map to a concrete code or config change.
- Consider both stock and crypto positions separately.

Respond ONLY with valid JSON matching this schema:
{
  "portfolio_grade": "A|B|C|D|F",
  "summary": "2-3 sentence overall assessment",
  "suggestions": [
    {
      "title": "Short issue title (imperative verb, e.g. 'Reduce TSLA position size')",
      "priority": "high|medium|low",
      "category": "risk|performance|strategy|config|watchlist",
      "body": "Detailed explanation with specific numbers and recommended changes. \
Use markdown formatting.",
      "labels": ["enhancement"]
    }
  ]
}
"""


class PortfolioReviewer:
    """Analyzes portfolio performance and produces suggestions as structured data."""

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
        """Run a full portfolio review and return structured suggestions.

        Returns a dict with keys: portfolio_grade, summary, suggestions.
        """
        prompt = self._build_review_prompt(portfolio, technicals)

        log.info("portfolio_review_started", model=self._model)

        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=REVIEW_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw_text = response.content[0].text  # type: ignore[union-attr]
        result = self._parse_review(raw_text)

        log.info(
            "portfolio_review_complete",
            grade=result.get("portfolio_grade", "?"),
            suggestion_count=len(result.get("suggestions", [])),
        )

        return result

    def _build_review_prompt(
        self,
        portfolio: PortfolioSnapshot,
        technicals: dict[str, dict[str, float]],
    ) -> str:
        """Build the review prompt with portfolio state and performance data."""
        positions_data: list[dict[str, Any]] = []
        for p in portfolio.positions:
            positions_data.append(
                {
                    "symbol": p.symbol,
                    "asset_class": p.asset_class.value,
                    "qty": p.qty,
                    "avg_entry_price": round(p.avg_entry_price, 2),
                    "current_price": round(p.current_price, 2),
                    "market_value": round(p.market_value, 2),
                    "unrealized_pl": round(p.unrealized_pl, 2),
                    "unrealized_pl_pct": round(p.unrealized_pl_pct * 100, 2),
                    "portfolio_weight_pct": round(portfolio.position_weight(p.symbol) * 100, 2),
                    "side": p.side,
                }
            )

        # Separate winners and losers for clarity
        winners = [p for p in positions_data if float(p["unrealized_pl"]) > 0]
        losers = [p for p in positions_data if float(p["unrealized_pl"]) < 0]
        flat = [p for p in positions_data if float(p["unrealized_pl"]) == 0]

        winners.sort(key=lambda x: float(x["unrealized_pl"]), reverse=True)
        losers.sort(key=lambda x: float(x["unrealized_pl"]))

        cash_pct = (portfolio.cash / portfolio.equity * 100) if portfolio.equity > 0 else 0
        stock_positions = [p for p in positions_data if p["asset_class"] == "us_equity"]
        crypto_positions = [p for p in positions_data if p["asset_class"] == "crypto"]

        stock_value = sum(float(p["market_value"]) for p in stock_positions)
        crypto_value = sum(float(p["market_value"]) for p in crypto_positions)

        return f"""## Portfolio Review Request

## Current Trading Configuration
- Strategy: {self._trading_config.strategy}
- Max position size: {self._trading_config.max_position_pct * 100:.0f}%
- Stop loss: {self._trading_config.stop_loss_pct * 100:.1f}%
- Take profit: {self._trading_config.take_profit_pct * 100:.1f}%
- Min cash reserve: {self._trading_config.min_cash_reserve_pct * 100:.0f}%
- Watchlist (stocks): {self._trading_config.watchlist}
- Watchlist (crypto): {self._trading_config.crypto_watchlist}
- Max daily trades: {self._trading_config.max_daily_trades}

## Portfolio Overview
- Total equity: ${portfolio.equity:,.2f}
- Cash: ${portfolio.cash:,.2f} ({cash_pct:.1f}%)
- Total positions: {portfolio.position_count}
- Total unrealized P/L: ${portfolio.total_unrealized_pl:,.2f}
- Stock allocation: ${stock_value:,.2f}
- Crypto allocation: ${crypto_value:,.2f}

## Top Winners
{json.dumps(winners[:5], indent=2) if winners else "None"}

## Top Losers
{json.dumps(losers[:5], indent=2) if losers else "None"}

## Flat Positions
{json.dumps(flat, indent=2) if flat else "None"}

## All Positions Detail
{json.dumps(positions_data, indent=2)}

## Technical Indicators (Current)
{
            json.dumps(
                {k: {ik: round(iv, 4) for ik, iv in v.items()} for k, v in technicals.items()},
                indent=2,
            )
        }

Analyze this portfolio and provide your review with specific, actionable suggestions as JSON.
"""

    def _parse_review(self, raw: str) -> dict[str, Any]:
        """Parse Claude's JSON review response."""
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        try:
            data: dict[str, Any] = json.loads(text)
        except json.JSONDecodeError:
            log.error("review_parse_error", raw=raw[:500])
            return {
                "portfolio_grade": "?",
                "summary": "Failed to parse AI review response.",
                "suggestions": [],
            }

        return data
