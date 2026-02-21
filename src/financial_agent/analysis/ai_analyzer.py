"""AI-powered analysis using Claude to interpret technical data and generate trade signals."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import anthropic
import structlog

from financial_agent.portfolio.models import AssetClass, SignalType, TradeSignal

if TYPE_CHECKING:
    from financial_agent.config import AIConfig, TradingConfig
    from financial_agent.portfolio.models import PortfolioSnapshot

log = structlog.get_logger()

SYSTEM_PROMPT = """\
You are an expert quantitative trading analyst. Your job is to analyze portfolio data \
and technical indicators to produce actionable trading signals for both stocks and \
cryptocurrencies.

Rules:
- Be conservative with confidence scores. Only use >0.8 for very strong signals.
- Always provide a clear reason for each signal.
- Consider the overall portfolio balance and diversification.
- Factor in risk management: stop losses, position sizing, correlation.
- If indicators are mixed or unclear, recommend HOLD.
- Never recommend more than 3 BUY signals at once to avoid over-trading.
- Consider the current strategy mode when making recommendations.

Crypto-specific rules:
- Crypto symbols contain "/" (e.g., BTC/USD, ETH/USD). Stock symbols do not.
- Crypto trades 24/7 — there is no market close.
- Crypto is more volatile than stocks — use wider stop losses (8-15% vs 3-5%).
- Treat crypto and stock allocations as separate buckets for diversification.
- Be especially cautious with altcoins; prefer BTC and ETH for larger positions.

Respond ONLY with valid JSON matching this schema:
{
  "analysis_summary": "Brief overall market assessment",
  "signals": [
    {
      "symbol": "AAPL",
      "signal": "buy|sell|hold",
      "confidence": 0.0-1.0,
      "reason": "Explanation of the signal",
      "target_weight": 0.05,
      "stop_loss": 150.00,
      "take_profit": 200.00
    }
  ]
}
"""


class AIAnalyzer:
    """Uses Claude to analyze market data and produce trade signals."""

    def __init__(self, ai_config: AIConfig, trading_config: TradingConfig) -> None:
        self._client = anthropic.Anthropic(api_key=ai_config.api_key)
        self._model = ai_config.model
        self._max_tokens = ai_config.max_tokens
        self._strategy = trading_config.strategy

    def analyze(
        self,
        portfolio: PortfolioSnapshot,
        technicals: dict[str, dict[str, float]],
    ) -> list[TradeSignal]:
        """Send portfolio + technical data to Claude and parse trade signals."""
        prompt = self._build_prompt(portfolio, technicals)

        log.info("ai_analysis_started", model=self._model, symbols=list(technicals.keys()))

        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw_text = response.content[0].text
        signals = self._parse_response(raw_text)

        log.info(
            "ai_analysis_complete",
            signal_count=len(signals),
            buy_count=sum(1 for s in signals if s.signal == SignalType.BUY),
            sell_count=sum(1 for s in signals if s.signal == SignalType.SELL),
        )

        return signals

    def _build_prompt(
        self,
        portfolio: PortfolioSnapshot,
        technicals: dict[str, dict[str, float]],
    ) -> str:
        """Build the analysis prompt with all relevant data."""
        positions_data = []
        for p in portfolio.positions:
            positions_data.append(
                {
                    "symbol": p.symbol,
                    "qty": p.qty,
                    "avg_entry": p.avg_entry_price,
                    "current_price": p.current_price,
                    "unrealized_pl_pct": round(p.unrealized_pl_pct * 100, 2),
                    "weight": round(portfolio.position_weight(p.symbol) * 100, 2),
                }
            )

        return f"""## Current Strategy Mode: {self._strategy}

## Portfolio Overview
- Equity: ${portfolio.equity:,.2f}
- Cash: ${portfolio.cash:,.2f} ({portfolio.cash / portfolio.equity * 100:.1f}% of equity)
- Positions: {portfolio.position_count}
- Total Unrealized P/L: ${portfolio.total_unrealized_pl:,.2f}

## Current Positions
{json.dumps(positions_data, indent=2)}

## Technical Indicators by Symbol
{
            json.dumps(
                {k: {ik: round(iv, 4) for ik, iv in v.items()} for k, v in technicals.items()},
                indent=2,
            )
        }

Analyze the above data and provide your trading signals as JSON.
"""

    def _parse_response(self, raw: str) -> list[TradeSignal]:
        """Parse Claude's JSON response into TradeSignal objects."""
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            log.error("ai_response_parse_error", raw=raw[:500])
            return []

        signals: list[TradeSignal] = []
        for entry in data.get("signals", []):
            try:
                symbol = entry["symbol"]
                asset_cls = AssetClass.CRYPTO if "/" in symbol else AssetClass.US_EQUITY
                signals.append(
                    TradeSignal(
                        symbol=symbol,
                        signal=SignalType(entry["signal"]),
                        confidence=float(entry["confidence"]),
                        reason=entry["reason"],
                        target_weight=entry.get("target_weight"),
                        stop_loss=entry.get("stop_loss"),
                        take_profit=entry.get("take_profit"),
                        asset_class=asset_cls,
                    )
                )
            except (KeyError, ValueError) as e:
                log.warning("skipping_invalid_signal", entry=entry, error=str(e))

        return signals
