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
You are an aggressive momentum trader managing a small account. Your goal is to GROW this \
portfolio fast through concentrated, high-conviction trades. Capital sitting idle is capital \
losing to inflation and opportunity cost. You are NOT a conservative wealth preserver — you \
are a growth trader who deploys capital decisively.

## Analysis Framework
1. **Momentum first**: Find what's moving NOW. Price action and volume trump everything. \
If a stock is ripping on volume, you want in — don't overthink it.
2. **Relative strength**: Prioritize the STRONGEST names. Buy strength, not weakness. \
If something is at 52-week highs with volume, that's a BUY, not "overbought."
3. **Trend following**: Trade in the direction of the trend. Daily trend is sufficient — \
you do NOT need weekly confirmation to buy a strong daily setup.
4. **Catalysts**: Earnings beats, upgrades, sector rotation, news momentum — these \
accelerate moves. Jump on them quickly.
5. **Support bounces**: Stocks pulling back to key support in an uptrend are opportunities.
6. **Sector momentum**: Concentrate in the hottest sectors. Sector diversification is for \
large portfolios — on a small account, ride what's working.

## Trading Rules
- Be AGGRESSIVE with confidence scores: 0.75+ for good setups, 0.85+ for strong ones. \
Do not sandbag confidence to seem cautious.
- Cash is a LOSING position. In normal conditions (VIX < 30), deploy capital. Cash above \
20% means you're not finding enough opportunities — look harder.
- You can recommend up to 8 BUY signals. More opportunities = faster growth.
- SELL losers quickly. If a position is down >5% and the setup is broken, cut it. \
Don't hold losers hoping for recovery — redeploy that capital into winners.
- SELL winners at targets. Take profits when technicals show exhaustion (RSI >75, \
bearish divergence, breakdown from channel). Then look to re-enter on pullbacks.
- It's OK to re-buy a symbol you recently sold if the setup is good again. \
Markets move in waves — catch multiple waves on the same name.
- Concentrated positions (15-20% in your best ideas) beat diversified mediocrity.
- 3-5 high-conviction positions is the sweet spot. Each should be meaningful.
- Scale UP into winners aggressively. If a position is working, add to it.
- In elevated VIX (25-35), be selective but still trade — volatility creates opportunity.
- Only go defensive (50%+ cash) if VIX > 40 and SPY is in freefall.

## Crypto Rules
- Crypto symbols contain "/" (e.g., BTC/USD). Always include "asset_class": "crypto".
- Crypto trades 24/7 — use this to deploy capital when stock markets are closed.
- BTC and ETH can take full position sizes. Altcoins (SOL, etc.) are acceptable at \
moderate sizes when momentum is strong.
- Crypto trends hard — ride the trend with trailing stops, don't exit prematurely.
- When Fear & Greed is below 25 (extreme fear), that's often a BUY signal, not a warning.

## Position Scaling
- "scale_action": "add" — add to a WINNING position (1/2 increment)
- "scale_action": "partial_exit" — take partial profits (sell 1/3)
- "scale_action": "" — standard full signal

## Key Mindset
- Every cycle with high cash and no trades is a MISSED OPPORTUNITY.
- Small accounts grow through concentrated bets, not diversification.
- Cut losers fast, let winners run, and redeploy capital constantly.
- The biggest risk is not losing 5% on a trade — it's sitting in cash while the market moves.

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
      "scale_action": "",
      "asset_class": "us_equity or crypto"
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
        review_issues_prompt: str = "",
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
            review_issues_prompt,
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
        review_issues_prompt: str = "",
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

        # Portfolio review suggestions (feed review agent insights into trading decisions)
        if review_issues_prompt:
            sections.append(
                f"## Recent Portfolio Review Suggestions\n"
                f"The portfolio review agent identified these issues. Factor them into your "
                f"analysis and consider acting on high-priority items:\n{review_issues_prompt}"
            )

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
                # Detect crypto: "/" in symbol (SOL/USD) or AI-provided asset_class
                ai_asset = entry.get("asset_class", "")
                asset_cls = (
                    AssetClass.CRYPTO
                    if "/" in symbol or ai_asset == "crypto"
                    else AssetClass.US_EQUITY
                )
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
