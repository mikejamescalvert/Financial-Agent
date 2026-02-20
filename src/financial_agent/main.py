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

    # Step 1: Check market status
    if not broker.is_market_open():
        log.info("market_closed", message="Market is closed. Skipping this run.")
        return

    # Step 2: Get portfolio snapshot
    portfolio = broker.get_portfolio_snapshot()
    log.info(
        "portfolio_loaded",
        equity=portfolio.equity,
        cash=portfolio.cash,
        positions=portfolio.position_count,
    )

    # Step 3: Get watchlist symbols (include existing positions)
    watchlist = [s.strip() for s in config.trading.watchlist.split(",")]
    held_symbols = [p.symbol for p in portfolio.positions]
    all_symbols = list(set(watchlist + held_symbols))

    # Step 4: Run technical analysis
    log.info("technical_analysis_started", symbols=all_symbols)
    bars = broker.get_historical_bars(all_symbols, days=60)
    technicals = technical.compute_indicators(bars)
    log.info("technical_analysis_complete", analyzed=len(technicals))

    # Step 5: AI analysis
    signals = ai.analyze(portfolio, technicals)

    # Step 6: Generate orders
    orders = engine.generate_orders(signals, portfolio)
    log.info("orders_generated", count=len(orders))

    # Step 7: Execute orders
    results = []
    for order in orders:
        result = broker.submit_order(order, dry_run=config.trading.dry_run)
        results.append(result)

    # Step 8: Summary
    summary = {
        "equity": portfolio.equity,
        "cash": portfolio.cash,
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
