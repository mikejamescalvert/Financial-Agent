"""Main entry point for the Financial Agent.

This is called by the GitHub Action on schedule. It:
1. Fetches the current portfolio state
2. Runs technical analysis on the watchlist
3. Sends everything to Claude for AI analysis
4. Generates trade orders from the signals
5. Executes trades (or logs them in dry-run mode)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime

import structlog

from financial_agent.analysis import AIAnalyzer
from financial_agent.broker import AlpacaBroker
from financial_agent.config import AppConfig
from financial_agent.portfolio.models import SignalType, TradeOrder, TradeSignal
from financial_agent.strategy import StrategyEngine, TechnicalAnalyzer
from financial_agent.utils.logging import setup_logging


def main() -> None:
    """Run one cycle of the trading agent."""
    config = AppConfig()
    setup_logging(config.log_level)
    log = structlog.get_logger()

    log.info("agent_started", strategy=config.trading.strategy, dry_run=config.trading.dry_run)

    # Initialize components
    broker = AlpacaBroker(config.broker)
    technical = TechnicalAnalyzer()
    ai = AIAnalyzer(config.ai, config.trading)
    engine = StrategyEngine(config.trading)

    # Step 1: Check market status (stocks only when open, crypto always)
    market_open = broker.is_market_open()
    log.info("market_status", market_open=market_open)

    # Step 2: Get portfolio snapshot
    portfolio = broker.get_portfolio_snapshot()
    log.info(
        "portfolio_loaded",
        equity=portfolio.equity,
        cash=portfolio.cash,
        positions=portfolio.position_count,
    )

    technicals: dict[str, dict[str, float]] = {}

    # Step 3a: Crypto pipeline (always runs)
    crypto_watchlist = [s.strip() for s in config.trading.crypto_watchlist.split(",")]
    held_crypto = [_normalize_crypto_symbol(p.symbol) for p in portfolio.crypto_positions()]
    all_crypto = list(set(crypto_watchlist + held_crypto))

    if all_crypto:
        log.info("crypto_analysis_started", symbols=all_crypto)
        crypto_bars = broker.get_crypto_historical_bars(all_crypto, days=90)
        crypto_technicals = technical.compute_indicators(crypto_bars)
        technicals.update(crypto_technicals)
        log.info("crypto_analysis_complete", analyzed=len(crypto_technicals))

    # Step 3b: Stock pipeline (only when market is open)
    if market_open:
        stock_watchlist = [s.strip() for s in config.trading.watchlist.split(",")]
        held_stocks = [p.symbol for p in portfolio.stock_positions()]
        all_stocks = list(set(stock_watchlist + held_stocks))

        log.info("stock_analysis_started", symbols=all_stocks)
        stock_bars = broker.get_historical_bars(all_stocks, days=90)
        stock_technicals = technical.compute_indicators(stock_bars)
        technicals.update(stock_technicals)
        log.info("stock_analysis_complete", analyzed=len(stock_technicals))
    else:
        log.info("stock_analysis_skipped", reason="market_closed")

    if not technicals:
        log.info("no_symbols_to_analyze", message="No technicals computed. Skipping.")
        return

    # Step 4: AI analysis (single pass with all technicals)
    signals, analysis_summary = ai.analyze(portfolio, technicals)

    # Step 5: Generate orders
    orders = engine.generate_orders(signals, portfolio, technicals)
    log.info("orders_generated", count=len(orders))

    # Step 6: Execute orders
    results = []
    for order in orders:
        result = broker.submit_order(order, dry_run=config.trading.dry_run)
        results.append(result)

    # Step 7: Summary
    summary = {
        "equity": portfolio.equity,
        "cash": portfolio.cash,
        "market_open": market_open,
        "analysis_summary": analysis_summary,
        "signals": {
            "buy": sum(1 for s in signals if s.signal == SignalType.BUY),
            "sell": sum(1 for s in signals if s.signal == SignalType.SELL),
            "hold": sum(1 for s in signals if s.signal == SignalType.HOLD),
        },
        "orders_submitted": len(results),
        "dry_run": config.trading.dry_run,
    }
    log.info("agent_complete", **summary)

    # Write outputs for GitHub Actions
    _write_github_output(summary)
    _write_step_summary(
        portfolio=portfolio,
        market_open=market_open,
        analysis_summary=analysis_summary,
        signals=signals,
        orders=orders,
        results=results,
        dry_run=config.trading.dry_run,
        strategy=config.trading.strategy,
    )


def _normalize_crypto_symbol(symbol: str) -> str:
    """Normalize crypto symbols to the 'XXX/YYY' format required by the data API.

    Alpaca positions use 'BTCUSD' but the crypto data API requires 'BTC/USD'.
    """
    if "/" in symbol:
        return symbol
    # Crypto pairs always end in USD — split before the currency suffix
    if symbol.endswith("USD"):
        return symbol[:-3] + "/USD"
    return symbol


def _write_github_output(summary: dict[str, object]) -> None:
    """Write summary to GITHUB_OUTPUT for use in subsequent workflow steps."""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"summary={json.dumps(summary)}\n")


def _write_step_summary(  # noqa: PLR0913
    *,
    portfolio: object,
    market_open: bool,
    analysis_summary: str,
    signals: list[TradeSignal],
    orders: list[TradeOrder],
    results: list[dict[str, object]],
    dry_run: bool,
    strategy: str,
) -> None:
    """Write a rich markdown summary to GITHUB_STEP_SUMMARY."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return

    from financial_agent.portfolio.models import PortfolioSnapshot

    assert isinstance(portfolio, PortfolioSnapshot)
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")
    market_status = "Open" if market_open else "Closed"
    mode = "DRY RUN" if dry_run else "LIVE"

    lines: list[str] = []
    lines.append(f"## Trading Agent Run — {now}")
    lines.append("")
    lines.append(f"**Mode:** {mode} | **Strategy:** {strategy} | **Market:** {market_status}")
    lines.append("")

    # Portfolio overview
    lines.append("### Portfolio")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Equity | ${portfolio.equity:,.2f} |")
    lines.append(f"| Cash | ${portfolio.cash:,.2f} |")
    lines.append(f"| Positions | {portfolio.position_count} |")
    lines.append(f"| Unrealized P/L | ${portfolio.total_unrealized_pl:,.2f} |")
    lines.append("")

    if portfolio.positions:
        lines.append("<details><summary>Current positions</summary>")
        lines.append("")
        lines.append("| Symbol | Qty | Entry | Current | P/L % | Class |")
        lines.append("|--------|-----|-------|---------|-------|-------|")
        for p in portfolio.positions:
            pl_pct = f"{p.unrealized_pl_pct * 100:+.1f}%"
            cls = "Crypto" if p.asset_class == "crypto" else "Stock"
            lines.append(
                f"| {p.symbol} | {p.qty:.4g} | ${p.avg_entry_price:,.2f} "
                f"| ${p.current_price:,.2f} | {pl_pct} | {cls} |"
            )
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # AI analysis
    lines.append("### AI Analysis")
    lines.append("")
    lines.append(f"> {analysis_summary}")
    lines.append("")

    # Signals
    buy_signals = [s for s in signals if s.signal == SignalType.BUY]
    sell_signals = [s for s in signals if s.signal == SignalType.SELL]
    hold_signals = [s for s in signals if s.signal == SignalType.HOLD]

    lines.append(
        f"### Signals ({len(buy_signals)} buy, {len(sell_signals)} sell, {len(hold_signals)} hold)"
    )
    lines.append("")

    actionable = [s for s in signals if s.signal != SignalType.HOLD]
    if actionable:
        lines.append("| Symbol | Signal | Confidence | Reason |")
        lines.append("|--------|--------|------------|--------|")
        for s in sorted(actionable, key=lambda x: x.confidence, reverse=True):
            emoji = "BUY" if s.signal == SignalType.BUY else "SELL"
            lines.append(f"| {s.symbol} | {emoji} | {s.confidence:.0%} | {s.reason} |")
        lines.append("")

    if hold_signals:
        lines.append(f"<details><summary>{len(hold_signals)} hold signals</summary>")
        lines.append("")
        lines.append("| Symbol | Confidence | Reason |")
        lines.append("|--------|------------|--------|")
        for s in hold_signals:
            lines.append(f"| {s.symbol} | {s.confidence:.0%} | {s.reason} |")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    # Orders
    lines.append(f"### Orders Executed ({len(orders)})")
    lines.append("")

    if orders:
        lines.append("| Symbol | Side | Qty | Confidence | Status |")
        lines.append("|--------|------|-----|------------|--------|")
        for order, result in zip(orders, results, strict=True):
            status = result.get("status", "unknown")
            side = order.side.upper()
            lines.append(
                f"| {order.symbol} | {side} | {order.qty:.4g} "
                f"| {order.signal_confidence:.0%} | {status} |"
            )
        lines.append("")
    else:
        lines.append("No orders generated this cycle.")
        lines.append("")

    with open(summary_file, "a") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log = structlog.get_logger()
        log.error("agent_fatal_error", error=str(e), exc_info=True)
        sys.exit(1)
