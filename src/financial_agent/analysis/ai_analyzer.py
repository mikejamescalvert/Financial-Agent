"""AI-powered analysis using Claude to interpret technical data and generate trade signals."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import anthropic
import structlog

from financial_agent.portfolio.models import AssetClass, SignalType, TradeSignal

if TYPE_CHECKING:
    from financial_agent.config import AIConfig, TradingConfig
    from financial_agent.data.models import MarketEnrichment
    from financial_agent.portfolio.models import PortfolioSnapshot

log = structlog.get_logger()

SYSTEM_PROMPT = """\
You are an expert quantitative trading analyst managing a multi-asset portfolio. Your job is to \
analyze portfolio data, technical indicators, fundamentals, macro context, news sentiment, and \
risk metrics to produce actionable trading signals.

## Analysis Framework
1. **Macro first**: Check VIX, market regime, and upcoming economic events. In risk-off \
environments, reduce confidence on all buy signals.
2. **Sector rotation**: Favor sectors gaining relative strength. Avoid overweight sectors.
3. **Multi-timeframe**: Weekly trend sets direction, daily provides entry timing. Only buy \
when the weekly trend aligns with the daily signal.
4. **Fundamentals filter**: Avoid stocks with deteriorating fundamentals (negative earnings \
growth, high debt, poor margins) unless there's a clear technical catalyst.
5. **Earnings awareness**: Never recommend buying within the earnings buffer zone.
6. **News catalyst**: Upgrade/downgrade news or insider buying can confirm or override technicals.
7. **Relative strength**: Prefer symbols in the top quartile of relative strength vs SPY.
8. **Support/resistance**: Factor in proximity to key levels for entry and exit timing.

## Risk Rules
- Be conservative with confidence scores. Only use >0.8 for very strong, multi-factor signals.
- Always provide a clear reason for each signal.
- Consider the overall portfolio balance, sector exposure, and correlation.
- If indicators are mixed or unclear, recommend HOLD.
- Never recommend more than 3 BUY signals at once to avoid over-trading.
- Consider the current strategy mode when making recommendations.
- If portfolio drawdown is elevated, bias toward defensive positioning.
- If a position's original trade thesis is invalidated, recommend SELL regardless of P/L.

## Crypto-specific rules
- Crypto symbols contain "/" (e.g., BTC/USD, ETH/USD). Stock symbols do not.
- Crypto trades 24/7 — there is no market close.
- Crypto is more volatile — use wider stop losses (8-15% vs 3-5%).
- Treat crypto and stock allocations as separate buckets for diversification.
- Be especially cautious with altcoins; prefer BTC and ETH for larger positions.
- When BTC dominance is rising, reduce altcoin exposure.
- When BTC is below its 50-day SMA, reduce confidence on ALL crypto buy signals.

## Position Scaling
You can recommend partial entries and exits:
- "scale_action": "add" — add to an existing position (1/3 increment)
- "scale_action": "partial_exit" — take partial profits (sell 1/3)
- "scale_action": "" — standard full signal

Respond ONLY with valid JSON matching this schema:
{
  "analysis_summary": "Brief overall market assessment including macro view",
  "signals": [
    {
      "symbol": "AAPL",
      "signal": "buy|sell|hold",
      "confidence": 0.0-1.0,
      "reason": "Multi-factor explanation of the signal",
      "target_weight": 0.05,
      "stop_loss": 150.00,
      "take_profit": 200.00,
      "scale_action": ""
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
        self._max_position_pct = trading_config.max_position_pct
        self._stop_loss_pct = trading_config.stop_loss_pct
        self._take_profit_pct = trading_config.take_profit_pct
        self._min_cash_reserve_pct = trading_config.min_cash_reserve_pct

    def analyze(
        self,
        portfolio: PortfolioSnapshot,
        technicals: dict[str, dict[str, float]],
        enrichment: MarketEnrichment | None = None,
        theses_prompt: str = "",
        equity_prompt: str = "",
        performance_prompt: str = "",
    ) -> tuple[list[TradeSignal], str]:
        """Send portfolio + technical data + enrichment to Claude and parse signals.

        Returns a tuple of (signals, analysis_summary).
        """
        prompt = self._build_prompt(
            portfolio,
            technicals,
            enrichment,
            theses_prompt,
            equity_prompt,
            performance_prompt,
        )

        log.info("ai_analysis_started", model=self._model, symbols=list(technicals.keys()))

        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw_text = response.content[0].text  # type: ignore[union-attr]
        signals, analysis_summary = self._parse_response(raw_text)

        log.info(
            "ai_analysis_complete",
            signal_count=len(signals),
            buy_count=sum(1 for s in signals if s.signal == SignalType.BUY),
            sell_count=sum(1 for s in signals if s.signal == SignalType.SELL),
            analysis_summary=analysis_summary,
        )

        return signals, analysis_summary

    def _build_prompt(
        self,
        portfolio: PortfolioSnapshot,
        technicals: dict[str, dict[str, float]],
        enrichment: MarketEnrichment | None,
        theses_prompt: str,
        equity_prompt: str,
        performance_prompt: str,
    ) -> str:
        """Build the analysis prompt with all available data."""
        sections: list[str] = []

        sections.append(f"## Current Strategy Mode: {self._strategy}")

        # Risk parameters
        sections.append(f"""## Risk Parameters
- Max position size: {self._max_position_pct * 100:.0f}% of portfolio
- Stop loss target: {self._stop_loss_pct * 100:.1f}%
- Take profit target: {self._take_profit_pct * 100:.1f}%
- Min cash reserve: {self._min_cash_reserve_pct * 100:.0f}% of portfolio""")

        # Portfolio overview
        positions_data = []
        for p in portfolio.positions:
            pos_info: dict[str, object] = {
                "symbol": p.symbol,
                "qty": p.qty,
                "avg_entry": p.avg_entry_price,
                "current_price": p.current_price,
                "unrealized_pl_pct": round(p.unrealized_pl_pct * 100, 2),
                "weight": round(portfolio.position_weight(p.symbol) * 100, 2),
            }
            if p.sector:
                pos_info["sector"] = p.sector
            positions_data.append(pos_info)

        cash_pct = round(portfolio.cash / portfolio.equity * 100, 1) if portfolio.equity > 0 else 0

        sections.append(f"""## Portfolio Overview
- Equity: ${portfolio.equity:,.2f}
- Cash: ${portfolio.cash:,.2f} ({cash_pct}% of equity)
- Positions: {portfolio.position_count}
- Total Unrealized P/L: ${portfolio.total_unrealized_pl:,.2f}""")

        # Sector exposure
        sector_exp = portfolio.sector_exposure()
        if sector_exp:
            exp_lines = [
                f"  - {sector}: {weight:.1%}"
                for sector, weight in sorted(sector_exp.items(), key=lambda x: x[1], reverse=True)
            ]
            sections.append("## Sector Exposure\n" + "\n".join(exp_lines))

        sections.append(f"## Current Positions\n{json.dumps(positions_data, indent=2)}")

        # Enrichment data (Issues #12-15, #26)
        if enrichment:
            self._add_enrichment_sections(sections, enrichment)

        # Trade thesis persistence (Issue #27)
        if theses_prompt:
            sections.append(f"## Active Trade Theses\n{theses_prompt}")

        # Equity / drawdown context
        if equity_prompt:
            sections.append(f"## Portfolio History & Drawdown\n{equity_prompt}")

        # Performance metrics (Issue #20)
        if performance_prompt:
            sections.append(f"## Performance Metrics\n{performance_prompt}")

        # Technical indicators
        rounded_technicals = {
            k: {ik: round(iv, 4) for ik, iv in v.items()} for k, v in technicals.items()
        }
        sections.append(
            f"## Technical Indicators by Symbol\n{json.dumps(rounded_technicals, indent=2)}"
        )

        sections.append("Analyze the above data and provide your trading signals as JSON.")
        return "\n\n".join(sections)

    def _add_enrichment_sections(self, sections: list[str], enrichment: MarketEnrichment) -> None:
        """Add market enrichment data sections to the prompt."""
        # Macro context (Issue #15)
        if enrichment.macro:
            m = enrichment.macro
            macro_lines = [
                f"- VIX: {m.vix_level or 'N/A'} ({m.vix_trend})",
                f"- Market regime: {m.market_regime}",
                f"- SPY trend: {m.spy_trend}",
            ]
            if m.ten_year_yield is not None:
                macro_lines.append(f"- 10Y yield: {m.ten_year_yield:.2f}%")
            if m.upcoming_events:
                macro_lines.append("- Upcoming events: " + ", ".join(m.upcoming_events[:5]))
            sections.append("## Macro Context\n" + "\n".join(macro_lines))

        # Crypto market structure (Issue #26)
        if enrichment.crypto:
            c = enrichment.crypto
            crypto_lines = []
            if c.btc_dominance is not None:
                crypto_lines.append(f"- BTC dominance: {c.btc_dominance:.1f}%")
            if c.fear_greed_index is not None:
                crypto_lines.append(f"- Fear & Greed: {c.fear_greed_index} ({c.fear_greed_label})")
            crypto_lines.append(f"- BTC trend: {c.btc_trend}")
            if crypto_lines:
                sections.append("## Crypto Market Structure\n" + "\n".join(crypto_lines))

        # Fundamentals (Issue #12)
        if enrichment.fundamentals:
            fund_data: dict[str, dict[str, object]] = {}
            for sym, fd in enrichment.fundamentals.items():
                entry: dict[str, object] = {}
                if fd.pe_ratio is not None:
                    entry["pe_ratio"] = round(fd.pe_ratio, 2)
                if fd.revenue_growth is not None:
                    entry["revenue_growth"] = f"{fd.revenue_growth:.1%}"
                if fd.profit_margin is not None:
                    entry["profit_margin"] = f"{fd.profit_margin:.1%}"
                if fd.debt_to_equity is not None:
                    entry["debt_to_equity"] = round(fd.debt_to_equity, 2)
                if fd.eps_ttm is not None:
                    entry["eps_ttm"] = round(fd.eps_ttm, 2)
                if entry:
                    fund_data[sym] = entry
            if fund_data:
                sections.append(f"## Fundamentals\n{json.dumps(fund_data, indent=2)}")

        # Earnings calendar (Issue #13)
        if enrichment.earnings:
            earn_lines = []
            for e in enrichment.earnings[:10]:
                earn_lines.append(
                    f"- {e.symbol}: reports in {e.days_until_earnings} days ({e.earnings_date})"
                )
            sections.append("## Upcoming Earnings\n" + "\n".join(earn_lines))

        # News sentiment (Issue #14)
        if enrichment.news:
            news_lines = []
            for sym, ns in enrichment.news.items():
                if ns.headline_count > 0:
                    sentiment_label = (
                        "positive"
                        if ns.avg_sentiment > 0.1
                        else "negative"
                        if ns.avg_sentiment < -0.1
                        else "neutral"
                    )
                    news_lines.append(
                        f"- {sym}: {sentiment_label} "
                        f"(score: {ns.avg_sentiment:+.2f}, "
                        f"{ns.headline_count} articles)"
                    )
                    # Include top headline
                    if ns.items:
                        news_lines.append(f"  Top: {ns.items[0].headline}")
            if news_lines:
                sections.append("## News & Sentiment\n" + "\n".join(news_lines))

    def _parse_response(self, raw: str) -> tuple[list[TradeSignal], str]:
        """Parse Claude's JSON response into TradeSignal objects and summary."""
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
            return [], ""

        analysis_summary = data.get("analysis_summary", "")

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
                        scale_action=entry.get("scale_action", ""),
                    )
                )
            except (KeyError, ValueError) as e:
                log.warning("skipping_invalid_signal", entry=entry, error=str(e))

        return signals, analysis_summary
