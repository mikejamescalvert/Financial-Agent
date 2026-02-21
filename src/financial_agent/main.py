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
import sys

import structlog

from financial_agent.analysis import AIAnalyzer
from financial_agent.broker import AlpacaBroker
from financial_agent.config import AppConfig
from financial_agent.portfolio.models import SignalType
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
    held_crypto = [p.symbol for p in portfolio.crypto_positions()]
    all_crypto = list(set(crypto_watchlist + held_crypto))

    if all_crypto:
        log.info("crypto_analysis_started", symbols=all_crypto)
        crypto_bars = broker.get_crypto_historical_bars(all_crypto, days=60)
        crypto_technicals = technical.compute_indicators(crypto_bars)
        technicals.update(crypto_technicals)
        log.info("crypto_analysis_complete", analyzed=len(crypto_technicals))

    # Step 3b: Stock pipeline (only when market is open)
    if market_open:
        stock_watchlist = [s.strip() for s in config.trading.watchlist.split(",")]
        held_stocks = [p.symbol for p in portfolio.stock_positions()]
        all_stocks = list(set(stock_watchlist + held_stocks))

        log.info("stock_analysis_started", symbols=all_stocks)
        stock_bars = broker.get_historical_bars(all_stocks, days=60)
        stock_technicals = technical.compute_indicators(stock_bars)
        technicals.update(stock_technicals)
        log.info("stock_analysis_complete", analyzed=len(stock_technicals))
    else:
        log.info("stock_analysis_skipped", reason="market_closed")

    if not technicals:
        log.info("no_symbols_to_analyze", message="No technicals computed. Skipping.")
        return

    # Step 4: AI analysis (single pass with all technicals)
    signals = ai.analyze(portfolio, technicals)

    # Step 5: Generate orders
    orders = engine.generate_orders(signals, portfolio)
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
        "signals": {
            "buy": sum(1 for s in signals if s.signal == SignalType.BUY),
            "sell": sum(1 for s in signals if s.signal == SignalType.SELL),
            "hold": sum(1 for s in signals if s.signal == SignalType.HOLD),
        },
        "orders_submitted": len(results),
        "dry_run": config.trading.dry_run,
    }
    log.info("agent_complete", **summary)

    # Write summary to GitHub Actions output if available
    _write_github_output(summary)


def _write_github_output(summary: dict) -> None:
    """Write summary to GITHUB_OUTPUT for use in subsequent workflow steps."""
    import os

    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"summary={json.dumps(summary)}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log = structlog.get_logger()
        log.error("agent_fatal_error", error=str(e), exc_info=True)
        sys.exit(1)
