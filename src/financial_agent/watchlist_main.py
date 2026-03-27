"""Entry point for the watchlist review agent.

This is called by the GitHub Action on a weekly schedule. It:
1. Fetches technical data for a broad screening universe
2. Sends everything to Claude to select the best targets
3. Updates TRADING_WATCHLIST and TRADING_CRYPTO_WATCHLIST GitHub Variables
4. Creates a GitHub issue summarizing the changes for audit
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import structlog

from financial_agent.broker import AlpacaBroker
from financial_agent.config import AppConfig
from financial_agent.review import WatchlistReviewer
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


def _update_github_variable(name: str, value: str) -> bool:
    """Update a GitHub Actions variable using gh CLI."""
    log = structlog.get_logger()
    success, output = _run_gh_command(["gh", "variable", "set", name, "--body", value])
    if success:
        log.info("github_variable_updated", name=name, value=value)
    return success


def _create_github_issue(title: str, body: str, labels: list[str]) -> bool:
    """Create a GitHub issue using the gh CLI."""
    cmd = ["gh", "issue", "create", "--title", title, "--body", body]
    for label in labels:
        cmd.extend(["--label", label])
    success, output = _run_gh_command(cmd)
    if success:
        log = structlog.get_logger()
        log.info("github_issue_created", title=title, url=output)
    return success


def _close_stale_watchlist_issues() -> int:
    """Close watchlist-review issues older than 7 days to prevent buildup."""
    log = structlog.get_logger()
    success, output = _run_gh_command(
        [
            "gh",
            "issue",
            "list",
            "--label",
            "watchlist-review",
            "--state",
            "open",
            "--limit",
            "100",
            "--json",
            "number,createdAt",
        ],
    )
    if not success or not output:
        return 0

    try:
        issues = json.loads(output)
    except json.JSONDecodeError:
        return 0

    from datetime import UTC, datetime, timedelta

    cutoff = datetime.now(tz=UTC) - timedelta(days=7)
    closed = 0
    for issue in issues:
        created = issue.get("createdAt", "")
        try:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if created_dt < cutoff:
            num = issue["number"]
            ok, _ = _run_gh_command(
                [
                    "gh",
                    "issue",
                    "close",
                    str(num),
                    "--reason",
                    "not planned",
                    "--comment",
                    "Auto-closed: superseded by newer watchlist review.",
                ],
            )
            if ok:
                closed += 1

    if closed:
        log.info("stale_watchlist_issues_closed", count=closed)
    return closed


def _ensure_labels_exist(labels: set[str]) -> None:
    """Create labels if they don't exist yet (errors are non-fatal)."""
    label_colors = {
        "watchlist-review": "BFD4F2",
        "watchlist": "BFD4F2",
        "automated": "C5DEF5",
    }
    for label in labels:
        color = label_colors.get(label, "EDEDED")
        cmd = ["gh", "label", "create", label, "--color", color, "--force"]
        _run_gh_command(cmd)


def main() -> None:
    """Run the watchlist review and update GitHub Variables."""
    config = AppConfig()
    setup_logging(config.log_level)
    log = structlog.get_logger()

    log.info("watchlist_agent_started")

    broker = AlpacaBroker(config.broker)
    technical = TechnicalAnalyzer()
    reviewer = WatchlistReviewer(config.ai, config.trading)

    # Fetch portfolio for context (held positions must stay on watchlist)
    portfolio = broker.get_portfolio_snapshot()
    log.info(
        "portfolio_loaded",
        equity=portfolio.equity,
        positions=portfolio.position_count,
    )

    # Build the full screening universe
    stock_universe = [s.strip() for s in config.trading.stock_universe.split(",") if s.strip()]
    crypto_universe = [s.strip() for s in config.trading.crypto_universe.split(",") if s.strip()]

    # Include currently held symbols even if not in the screening universe
    held_stocks = [p.symbol for p in portfolio.stock_positions()]
    held_crypto = [p.symbol for p in portfolio.crypto_positions()]
    all_stocks = list(set(stock_universe + held_stocks))
    all_crypto = list(set(crypto_universe + held_crypto))

    log.info(
        "screening_universe",
        stocks=len(all_stocks),
        crypto=len(all_crypto),
    )

    # Fetch technicals for the full universe
    technicals: dict[str, dict[str, float]] = {}

    if all_crypto:
        try:
            hist_days = config.trading.historical_days
            crypto_bars = broker.get_crypto_historical_bars(all_crypto, days=hist_days)
            crypto_technicals = technical.compute_indicators(crypto_bars)
            technicals.update(crypto_technicals)
            log.info("crypto_screening_complete", analyzed=len(crypto_technicals))
        except Exception as e:
            log.warning("crypto_screening_failed", error=str(e))

    if all_stocks:
        try:
            stock_bars = broker.get_historical_bars(all_stocks, days=hist_days)
            stock_technicals = technical.compute_indicators(stock_bars)
            technicals.update(stock_technicals)
            log.info("stock_screening_complete", analyzed=len(stock_technicals))
        except Exception as e:
            log.warning("stock_screening_failed", error=str(e))

    if not technicals:
        log.info("no_data", message="Could not fetch any screening data. Skipping.")
        return

    # Run the AI watchlist review
    result = reviewer.review(portfolio, technicals)

    summary = result.get("summary", "No summary available.")
    new_stocks = result.get("stock_watchlist", [])
    new_crypto = result.get("crypto_watchlist", [])
    changes = result.get("changes", [])

    if not new_stocks and not new_crypto:
        log.warning("empty_watchlist", message="AI returned empty watchlists. Skipping update.")
        return

    # Enforce: held positions must always stay on the watchlist
    for sym in held_stocks:
        if sym not in new_stocks:
            log.info("watchlist_held_position_preserved", symbol=sym)
            new_stocks.append(sym)
    for sym in held_crypto:
        normalized = sym if "/" in sym else (sym[:-3] + "/USD" if sym.endswith("USD") else sym)
        if normalized not in new_crypto:
            log.info("watchlist_held_crypto_preserved", symbol=normalized)
            new_crypto.append(normalized)

    # Get current watchlists for comparison
    old_stocks = [s.strip() for s in config.trading.watchlist.split(",")]
    old_crypto = [s.strip() for s in config.trading.crypto_watchlist.split(",")]

    stocks_added = set(new_stocks) - set(old_stocks)
    stocks_removed = set(old_stocks) - set(new_stocks)
    crypto_added = set(new_crypto) - set(old_crypto)
    crypto_removed = set(old_crypto) - set(new_crypto)

    has_changes = stocks_added or stocks_removed or crypto_added or crypto_removed

    if not has_changes:
        log.info("no_watchlist_changes", message="AI kept the same watchlist. No updates needed.")
        _write_github_output({"summary": summary, "changed": False})
        return

    # Update GitHub Variables
    stock_str = ",".join(new_stocks)
    crypto_str = ",".join(new_crypto)

    stock_updated = _update_github_variable("TRADING_WATCHLIST", stock_str)
    crypto_updated = _update_github_variable("TRADING_CRYPTO_WATCHLIST", crypto_str)

    log.info(
        "watchlist_updated",
        stock_updated=stock_updated,
        crypto_updated=crypto_updated,
        new_stocks=new_stocks,
        new_crypto=new_crypto,
    )

    # Close stale watchlist issues before creating new ones
    _close_stale_watchlist_issues()

    # Create an audit issue summarizing changes
    _ensure_labels_exist({"watchlist-review", "watchlist", "automated"})

    changes_md = ""
    for c in changes:
        action = c.get("action", "?")
        symbol = c.get("symbol", "?")
        reason = c.get("reason", "")
        icon = {"add": "+", "remove": "-", "keep": "="}.get(action, "?")
        changes_md += f"- `[{icon}]` **{symbol}** ({action}): {reason}\n"

    issue_body = f"""## Watchlist Review Update

{summary}

### Stock Watchlist
**Before:** `{",".join(old_stocks)}`
**After:** `{stock_str}`

| Added | Removed |
|-------|---------|
| {", ".join(sorted(stocks_added)) or "None"} | {", ".join(sorted(stocks_removed)) or "None"} |

### Crypto Watchlist
**Before:** `{",".join(old_crypto)}`
**After:** `{crypto_str}`

| Added | Removed |
|-------|---------|
| {", ".join(sorted(crypto_added)) or "None"} | {", ".join(sorted(crypto_removed)) or "None"} |

### Change Details
{changes_md}

---

<details>
<summary>Variables updated</summary>

- `TRADING_WATCHLIST` = `{stock_str}` ({"updated" if stock_updated else "FAILED"})
- `TRADING_CRYPTO_WATCHLIST` = `{crypto_str}` ({"updated" if crypto_updated else "FAILED"})

</details>

_This issue was automatically created by the watchlist review agent._
"""

    _create_github_issue(
        title=f"Watchlist update: +{len(stocks_added) + len(crypto_added)} "
        f"-{len(stocks_removed) + len(crypto_removed)} symbols",
        body=issue_body,
        labels=["watchlist-review", "watchlist", "automated"],
    )

    _write_github_output(
        {
            "summary": summary,
            "changed": True,
            "stocks": new_stocks,
            "crypto": new_crypto,
        }
    )

    log.info("watchlist_agent_complete")


def _write_github_output(data: dict[str, object]) -> None:
    """Write summary to GITHUB_OUTPUT for workflow visibility."""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a") as f:
            f.write(f"summary={json.dumps(data)}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log = structlog.get_logger()
        log.error("watchlist_agent_fatal_error", error=str(e), exc_info=True)
        sys.exit(1)
