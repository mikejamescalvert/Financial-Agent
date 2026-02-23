"""Main entry point for the Financial Agent.

This is called by the GitHub Action on schedule. It:
1. Fetches the current portfolio state
2. Fetches market enrichment data (fundamentals, earnings, news, macro, crypto)
3. Runs technical analysis on the watchlist
4. Checks trailing stops and drawdown circuit breaker
5. Sends everything to Claude for AI analysis
6. Generates trade orders from the signals
7. Executes trades (or logs them in dry-run mode)
8. Persists trade theses and equity history
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
from financial_agent.data.models import MarketEnrichment
from financial_agent.data.sector_map import get_sector
from financial_agent.performance import PerformanceTracker, TradeRecord
from financial_agent.persistence import EquityTracker, ThesisStore, TradeThesis
from financial_agent.portfolio.models import SignalType, TradeOrder, TradeSignal
from financial_agent.risk.drawdown import DrawdownCircuitBreaker
from financial_agent.risk.volatility import VolatilitySizer
from financial_agent.strategy import StrategyEngine, TechnicalAnalyzer
from financial_agent.utils.logging import setup_logging


def main() -> None:  # noqa: PLR0912, PLR0915
    """Run one cycle of the trading agent."""
    config = AppConfig()
    setup_logging(config.log_level)
    log = structlog.get_logger()

    log.info("agent_started", strategy=config.trading.strategy, dry_run=config.trading.dry_run)

    # Initialize core components
    broker = AlpacaBroker(config.broker)
    technical = TechnicalAnalyzer()

    # Initialize persistence (Issue #27, #17, #20)
    thesis_store = ThesisStore(config.data.data_dir)
    equity_tracker = EquityTracker(config.data.data_dir)
    perf_tracker = PerformanceTracker(config.data.data_dir)

    # Initialize risk management (Issue #17, #28)
    drawdown_breaker = DrawdownCircuitBreaker(peak_equity=equity_tracker.peak())
    vol_sizer = VolatilitySizer(risk_budget_pct=config.data.risk_budget_pct)

    # Initialize AI and strategy engine
    ai = AIAnalyzer(config.ai, config.trading)
    engine = StrategyEngine(
        config.trading,
        data_config=config.data,
        drawdown_breaker=drawdown_breaker,
        volatility_sizer=vol_sizer,
    )

    # Step 1: Check market status
    market_open = broker.is_market_open()
    log.info("market_status", market_open=market_open)

    # Step 2: Get portfolio snapshot
    portfolio = broker.get_portfolio_snapshot()

    # Enrich positions with sector data (Issue #16)
    for pos in portfolio.positions:
        pos.sector = get_sector(pos.symbol)

    log.info(
        "portfolio_loaded",
        equity=portfolio.equity,
        cash=portfolio.cash,
        positions=portfolio.position_count,
    )

    # Record equity for drawdown tracking (Issue #17, #20)
    equity_tracker.record(portfolio.equity, portfolio.cash, portfolio.position_count)

    # Step 3: Fetch market enrichment data (Issues #12-15, #26)
    enrichment = _fetch_enrichment(config, portfolio, log)

    # Step 4: Technical analysis
    technicals: dict[str, dict[str, float]] = {}
    hist_days = config.trading.historical_days

    # Crypto pipeline (always runs)
    crypto_watchlist = [s.strip() for s in config.trading.crypto_watchlist.split(",")]
    held_crypto = [_normalize_crypto_symbol(p.symbol) for p in portfolio.crypto_positions()]
    all_crypto = list(set(crypto_watchlist + held_crypto))

    if all_crypto:
        log.info("crypto_analysis_started", symbols=all_crypto)
        crypto_bars = broker.get_crypto_historical_bars(all_crypto, days=hist_days)
        crypto_technicals = technical.compute_indicators(crypto_bars)
        technicals.update(crypto_technicals)
        log.info("crypto_analysis_complete", analyzed=len(crypto_technicals))

    # Stock pipeline (only when market is open)
    if market_open:
        stock_watchlist = [s.strip() for s in config.trading.watchlist.split(",")]
        held_stocks = [p.symbol for p in portfolio.stock_positions()]
        all_stocks = list(set(stock_watchlist + held_stocks))

        log.info("stock_analysis_started", symbols=all_stocks)
        stock_bars = broker.get_historical_bars(all_stocks, days=hist_days)
        stock_technicals = technical.compute_indicators(stock_bars)

        # Add relative strength rankings (Issue #29)
        if "SPY" not in all_stocks:
            try:
                spy_bars = broker.get_historical_bars(["SPY"], days=hist_days)
                spy_tech = technical.compute_indicators(spy_bars)
                stock_technicals.update(spy_tech)
            except Exception as e:  # noqa: BLE001
                log.debug("spy_benchmark_fetch_failed", error=str(e))
        stock_technicals = technical.compute_relative_strength(stock_technicals, "SPY")

        technicals.update(stock_technicals)
        log.info("stock_analysis_complete", analyzed=len(stock_technicals))
    else:
        log.info("stock_analysis_skipped", reason="market_closed")

    if not technicals:
        log.info("no_symbols_to_analyze", message="No technicals computed. Skipping.")
        return

    # Step 5: Check trailing stops (Issue #23)
    trailing_signals = engine.check_trailing_stops(portfolio, technicals)
    if trailing_signals:
        log.info("trailing_stops_triggered", count=len(trailing_signals))

    # Step 6: AI analysis with all enrichment data
    theses_prompt = thesis_store.format_for_prompt()
    equity_prompt = equity_tracker.format_for_prompt()
    perf_prompt = perf_tracker.format_for_prompt(equity_tracker.daily_returns(30))

    signals, analysis_summary = ai.analyze(
        portfolio,
        technicals,
        enrichment=enrichment,
        theses_prompt=theses_prompt,
        equity_prompt=equity_prompt,
        performance_prompt=perf_prompt,
    )

    # Merge trailing stop signals with AI signals
    all_signals = trailing_signals + signals

    # Step 7: Generate orders
    orders = engine.generate_orders(all_signals, portfolio, technicals, enrichment)
    log.info("orders_generated", count=len(orders))

    # Step 8: Execute orders
    results = []
    for order in orders:
        result = broker.submit_order(order, dry_run=config.trading.dry_run)
        results.append(result)

        # Only record successful trades
        if result.get("status") == "failed":
            log.warning("order_failed_skipping_record", symbol=order.symbol)
            continue

        # Record trade and update thesis (Issues #27, #20)
        _record_trade(order, result, thesis_store, perf_tracker, signals)

    # Step 9: Summary
    summary: dict[str, object] = {
        "equity": portfolio.equity,
        "cash": portfolio.cash,
        "market_open": market_open,
        "analysis_summary": analysis_summary,
        "signals": {
            "buy": sum(1 for s in all_signals if s.signal == SignalType.BUY),
            "sell": sum(1 for s in all_signals if s.signal == SignalType.SELL),
            "hold": sum(1 for s in all_signals if s.signal == SignalType.HOLD),
        },
        "orders_submitted": len(results),
        "dry_run": config.trading.dry_run,
        "drawdown_pct": round(equity_tracker.current_drawdown(portfolio.equity) * 100, 2),
    }
    log.info("agent_complete", **summary)

    _write_github_output(summary)
    _write_step_summary(
        portfolio=portfolio,
        market_open=market_open,
        analysis_summary=analysis_summary,
        signals=all_signals,
        orders=orders,
        results=results,
        dry_run=config.trading.dry_run,
        strategy=config.trading.strategy,
        enrichment=enrichment,
        drawdown_pct=equity_tracker.current_drawdown(portfolio.equity),
    )


def _fetch_enrichment(
    config: AppConfig,
    portfolio: object,
    log: object,
) -> MarketEnrichment:
    """Fetch all market enrichment data, gracefully handling failures."""
    enrichment = MarketEnrichment()

    from financial_agent.portfolio.models import PortfolioSnapshot

    assert isinstance(portfolio, PortfolioSnapshot)

    watchlist_symbols = [s.strip() for s in config.trading.watchlist.split(",")]
    held_symbols = [p.symbol for p in portfolio.stock_positions()]
    all_symbols = list(set(watchlist_symbols + held_symbols))[:20]  # Limit API calls

    _log = structlog.get_logger()

    # Fundamentals (Issue #12)
    if config.data.fmp_api_key:
        try:
            from financial_agent.data.fundamentals import FundamentalsProvider

            fund_provider = FundamentalsProvider(api_key=config.data.fmp_api_key)
            enrichment.fundamentals = fund_provider.fetch(all_symbols[:10])
        except Exception as e:  # noqa: BLE001
            _log.debug("fundamentals_fetch_failed", error=str(e))

    # Earnings calendar (Issue #13)
    if config.data.fmp_api_key:
        try:
            from financial_agent.data.earnings import EarningsProvider

            earn_provider = EarningsProvider(api_key=config.data.fmp_api_key)
            enrichment.earnings = earn_provider.fetch(all_symbols)
        except Exception as e:  # noqa: BLE001
            _log.debug("earnings_fetch_failed", error=str(e))

    # News sentiment (Issue #14)
    if config.data.finnhub_api_key:
        try:
            from financial_agent.data.news import NewsProvider

            news_provider = NewsProvider(api_key=config.data.finnhub_api_key)
            enrichment.news = news_provider.fetch(all_symbols[:5])
        except Exception as e:  # noqa: BLE001
            _log.debug("news_fetch_failed", error=str(e))

    # Macro context (Issue #15)
    try:
        from financial_agent.data.macro import MacroProvider

        macro_provider = MacroProvider()
        enrichment.macro = macro_provider.fetch()
    except Exception as e:  # noqa: BLE001
        _log.debug("macro_fetch_failed", error=str(e))

    # Crypto market structure (Issue #26)
    try:
        from financial_agent.data.crypto_market import CryptoMarketProvider

        crypto_provider = CryptoMarketProvider()
        enrichment.crypto = crypto_provider.fetch()
    except Exception as e:  # noqa: BLE001
        _log.debug("crypto_market_fetch_failed", error=str(e))

    return enrichment


def _record_trade(
    order: TradeOrder,
    result: dict[str, object],
    thesis_store: ThesisStore,
    perf_tracker: PerformanceTracker,
    signals: list[TradeSignal],
) -> None:
    """Record a trade in the journal and manage thesis lifecycle."""
    now = datetime.now(tz=UTC).isoformat()

    # Record in trade journal (Issue #20)
    perf_tracker.record_trade(
        TradeRecord(
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            price=order.limit_price or 0.0,
            timestamp=now,
            reason=order.reason,
            confidence=order.signal_confidence,
            order_type=order.order_type.value,
        )
    )

    # Manage trade thesis (Issue #27)
    if order.side == "buy":
        # Find matching signal for thesis details
        matching = [s for s in signals if s.symbol == order.symbol]
        signal = matching[0] if matching else None

        thesis = TradeThesis(
            symbol=order.symbol,
            signal_type="buy",
            entry_price=order.limit_price or 0.0,
            entry_date=now[:10],
            reason=order.reason,
            target_price=signal.take_profit if signal else None,
            stop_loss=signal.stop_loss if signal else None,
            confidence=order.signal_confidence,
        )
        thesis_store.save_thesis(thesis)
    elif order.side == "sell":
        existing = thesis_store.get_thesis(order.symbol)
        if existing:
            thesis_store.close_thesis(order.symbol, reason=order.reason)


def _normalize_crypto_symbol(symbol: str) -> str:
    """Normalize crypto symbols to the 'XXX/YYY' format required by the data API."""
    if "/" in symbol:
        return symbol
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
    enrichment: MarketEnrichment | None = None,
    drawdown_pct: float = 0.0,
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
    if drawdown_pct > 0.01:
        lines.append(f"**Drawdown:** {drawdown_pct:.1%}")
    lines.append("")

    # Macro context
    if enrichment and enrichment.macro:
        m = enrichment.macro
        lines.append(
            f"**Macro:** VIX {m.vix_level or 'N/A'} ({m.vix_trend}) | "
            f"Regime: {m.market_regime} | SPY: {m.spy_trend}"
        )
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
        lines.append("| Symbol | Qty | Entry | Current | P/L % | Sector | Class |")
        lines.append("|--------|-----|-------|---------|-------|--------|-------|")
        for p in portfolio.positions:
            pl_pct = f"{p.unrealized_pl_pct * 100:+.1f}%"
            cls = "Crypto" if p.asset_class == "crypto" else "Stock"
            sector = p.sector or "-"
            lines.append(
                f"| {p.symbol} | {p.qty:.4g} | ${p.avg_entry_price:,.2f} "
                f"| ${p.current_price:,.2f} | {pl_pct} | {sector} | {cls} |"
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
        lines.append("| Symbol | Side | Qty | Type | Confidence | Status |")
        lines.append("|--------|------|-----|------|------------|--------|")
        for order, result in zip(orders, results, strict=True):
            status = result.get("status", "unknown")
            side = order.side.upper()
            otype = order.order_type.value
            lines.append(
                f"| {order.symbol} | {side} | {order.qty:.4g} | {otype} "
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
