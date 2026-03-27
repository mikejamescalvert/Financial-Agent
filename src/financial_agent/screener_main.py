"""Entry point for the daily pre-market screener.

Runs daily before market open. Performs a lightweight scan of the broad universe
for unusual volume, big movers, breakouts, and sector momentum. Proposes mid-week
watchlist additions without waiting for the weekly review.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import structlog

from financial_agent.broker import AlpacaBroker
from financial_agent.config import AppConfig
from financial_agent.data.sector_map import get_sector
from financial_agent.strategy import TechnicalAnalyzer
from financial_agent.utils.logging import setup_logging


def _run_gh_command(cmd: list[str]) -> tuple[bool, str]:
    """Run a gh CLI command. Returns (success, output_or_error)."""
    log = structlog.get_logger()
    try:
        result = subprocess.run(  # noqa: S603, S607
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            log.error("gh_command_failed", cmd=cmd[:3], stderr=result.stderr.strip())
            return False, result.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log.error("gh_command_error", cmd=cmd[:3], error=str(e))
        return False, str(e)


def main() -> None:
    """Run the daily pre-market screener."""
    config = AppConfig()
    setup_logging(config.log_level)
    log = structlog.get_logger()

    log.info("screener_started")

    broker = AlpacaBroker(config.broker)
    technical = TechnicalAnalyzer()

    # Fetch full stock universe
    stock_universe = [s.strip() for s in config.trading.stock_universe.split(",") if s.strip()]
    current_watchlist = {s.strip() for s in config.trading.watchlist.split(",")}

    log.info("screening_universe", total=len(stock_universe))

    if not stock_universe:
        log.info("screener_skip", reason="empty stock universe")
        _write_github_output({"alerts": 0})
        return

    # Fetch technical data for full universe
    try:
        bars = broker.get_historical_bars(stock_universe, days=config.trading.historical_days)
        technicals = technical.compute_indicators(bars)
    except Exception as e:
        log.error("screening_data_failed", error=str(e))
        return

    if not technicals:
        log.info("no_screening_data")
        return

    # Add relative strength
    technicals = technical.compute_relative_strength(technicals, "SPY")

    # Fetch VIX for adaptive thresholds
    vix_level: float | None = None
    try:
        from financial_agent.data.macro import MacroProvider

        macro = MacroProvider().fetch()
        vix_level = macro.vix_level
    except Exception:
        log.debug("screener_vix_fetch_failed", exc_info=True)

    # Adaptive thresholds based on market volatility
    if vix_level is not None and vix_level < 15:
        vol_thresh, move_thresh, rs_thresh = 3.0, 5.0, 85
    elif vix_level is not None and vix_level > 25:
        vol_thresh, move_thresh, rs_thresh = 1.5, 2.0, 70
    else:
        vol_thresh, move_thresh, rs_thresh = 2.0, 3.0, 80

    log.info("screener_thresholds", vix=vix_level, vol=vol_thresh, move=move_thresh, rs=rs_thresh)

    # Screen for actionable setups
    alerts: list[dict[str, str]] = []

    for symbol, ind in technicals.items():
        if symbol in ("SPY", "QQQ", "IWM"):
            continue

        reasons: list[str] = []

        # Unusual volume
        rel_vol = ind.get("relative_volume", 0)
        if rel_vol >= vol_thresh:
            reasons.append(f"unusual volume ({rel_vol:.1f}x avg)")

        # Big daily move
        daily_ret = abs(ind.get("daily_return_pct", 0))
        if daily_ret >= move_thresh:
            direction = "up" if ind.get("daily_return_pct", 0) > 0 else "down"
            reasons.append(f"big move {direction} ({daily_ret:.1f}%)")

        # Near 52-week high (within 3%)
        pct_from_high = ind.get("pct_from_52w_high", -100)
        if pct_from_high > -3.0:
            reasons.append(f"near 52w high ({pct_from_high:+.1f}%)")

        # Strong relative strength
        rs_rank = ind.get("rs_rank_pct", 0)
        if rs_rank >= rs_thresh:
            reasons.append(f"strong RS (top {100 - rs_rank:.0f}%)")

        # Price above 200-day SMA with positive MACD
        above_200 = ind.get("price_vs_sma200", 0) > 0
        macd_positive = ind.get("macd_histogram", 0) > 0
        if above_200 and macd_positive and rs_rank >= 60:
            reasons.append("bullish structure (>200SMA, MACD+)")

        if reasons and symbol not in current_watchlist:
            alerts.append(
                {
                    "symbol": symbol,
                    "sector": get_sector(symbol),
                    "reasons": ", ".join(reasons),
                    "rs_rank": f"{rs_rank:.0f}",
                }
            )

    alerts.sort(key=lambda a: float(a["rs_rank"]), reverse=True)
    top_alerts = alerts[:10]

    log.info("screening_complete", alerts=len(top_alerts))

    if not top_alerts:
        log.info("no_screener_alerts")
        _write_github_output({"alerts": 0})
        return

    # Create GitHub issue with screening results
    alert_lines = []
    for a in top_alerts:
        alert_lines.append(f"| {a['symbol']} | {a['sector']} | {a['reasons']} | {a['rs_rank']} |")

    issue_body = f"""## Daily Pre-Market Screen

Scanned {len(technicals)} symbols from the broad universe.

### Top Watchlist Candidates

| Symbol | Sector | Signals | RS Rank |
|--------|--------|---------|---------|
{chr(10).join(alert_lines)}

### Recommended Action
Review these candidates for potential watchlist addition. Symbols showing
multiple signals (unusual volume + strong RS + bullish structure) are
the highest priority.

_This issue was automatically created by the daily screener._
"""

    cmd = [
        "gh",
        "issue",
        "create",
        "--title",
        f"Daily screen: {len(top_alerts)} candidates spotted",
        "--body",
        issue_body,
        "--label",
        "screener",
        "--label",
        "automated",
    ]
    _run_gh_command(cmd)

    # Auto-add top 3 screener picks to watchlist for immediate trading
    top_picks = [a["symbol"] for a in top_alerts[:3] if a["symbol"] not in current_watchlist]
    if top_picks:
        expanded = ",".join(sorted(current_watchlist | set(top_picks)))
        try:
            cmd_var = ["gh", "variable", "set", "TRADING_WATCHLIST", "--body", expanded]
            ok, _ = _run_gh_command(cmd_var)
            if ok:
                log.info("screener_watchlist_expanded", added=top_picks, new_watchlist=expanded)
        except Exception:
            log.warning("screener_watchlist_update_failed", exc_info=True)

    _write_github_output({"alerts": len(top_alerts), "auto_added": top_picks})
    log.info("screener_complete")


def _write_github_output(data: dict[str, object]) -> None:
    """Write summary to GITHUB_OUTPUT."""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"summary={json.dumps(data)}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log = structlog.get_logger()
        log.error("screener_fatal_error", error=str(e), exc_info=True)
        sys.exit(1)
