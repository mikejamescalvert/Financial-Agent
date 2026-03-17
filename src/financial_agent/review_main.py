"""Entry point for the daily portfolio review agent.

This is called by the GitHub Action on a daily schedule. It:
1. Fetches the current portfolio state and technical indicators
2. Sends everything to Claude for a performance review
3. Creates GitHub issues with actionable improvement suggestions
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import structlog

from financial_agent.broker import AlpacaBroker
from financial_agent.config import AppConfig
from financial_agent.review import PortfolioReviewer
from financial_agent.strategy import TechnicalAnalyzer
from financial_agent.utils.logging import setup_logging


def _run_gh_command(cmd: list[str], timeout: int = 30) -> tuple[bool, str]:
    """Run a gh CLI command and return (success, stdout)."""
    try:
        result = subprocess.run(  # noqa: S603, S607
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, ""


def _get_open_review_issues() -> tuple[set[str], list[str]]:
    """Get categories and titles of open portfolio-review issues for deduplication.

    Returns a tuple of (category_set, title_list) from open portfolio-review issues.
    """
    log = structlog.get_logger()
    success, output = _run_gh_command(
        [
            "gh",
            "issue",
            "list",
            "--label",
            "portfolio-review",
            "--state",
            "open",
            "--limit",
            "30",
            "--json",
            "labels,title",
        ],
    )
    if not success or not output:
        return set(), []

    try:
        issues = json.loads(output)
    except json.JSONDecodeError:
        return set(), []

    # Extract category labels from existing open issues
    category_labels = {"risk", "performance", "strategy", "config", "watchlist"}
    existing_categories: set[str] = set()
    existing_titles: list[str] = []
    for issue in issues:
        existing_titles.append(issue.get("title", "").lower())
        for label in issue.get("labels", []):
            name = label.get("name", "") if isinstance(label, dict) else str(label)
            if name in category_labels:
                existing_categories.add(name)

    log.info(
        "existing_review_issues",
        categories=sorted(existing_categories),
        open_issues=len(issues),
    )
    return existing_categories, existing_titles


def _is_duplicate_title(new_title: str, existing_titles: list[str]) -> bool:
    """Check if a new issue title is too similar to an existing open issue.

    Uses keyword overlap: if 50%+ of significant words in the new title appear
    in an existing title, it's considered a duplicate.
    """
    stop_words = {
        "a",
        "an",
        "the",
        "to",
        "for",
        "of",
        "in",
        "on",
        "and",
        "or",
        "with",
        "from",
        "by",
        "at",
        "is",
        "it",
        "as",
        "be",
        "this",
        "that",
        "into",
        "current",
        "based",
    }
    new_words = {w for w in new_title.lower().split() if w not in stop_words and len(w) > 2}
    if not new_words:
        return False

    for existing in existing_titles:
        existing_words = {w for w in existing.lower().split() if w not in stop_words and len(w) > 2}
        if not existing_words:
            continue
        overlap = new_words & existing_words
        if len(overlap) >= len(new_words) * 0.5:
            return True

    return False


def _close_stale_review_issues() -> int:
    """Close portfolio-review issues older than 5 days to prevent buildup."""
    log = structlog.get_logger()
    success, output = _run_gh_command(
        [
            "gh",
            "issue",
            "list",
            "--label",
            "portfolio-review",
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

    cutoff = datetime.now(tz=UTC) - timedelta(days=5)
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
                    "Auto-closed: superseded by newer portfolio review.",
                ],
            )
            if ok:
                closed += 1

    if closed:
        log.info("stale_issues_closed", count=closed)
    return closed


def _create_github_issue(title: str, body: str, labels: list[str]) -> bool:
    """Create a GitHub issue using the gh CLI.

    Returns True if the issue was created successfully.
    """
    log = structlog.get_logger()

    cmd = ["gh", "issue", "create", "--title", title, "--body", body]
    for label in labels:
        cmd.extend(["--label", label])

    success, output = _run_gh_command(cmd)
    if success:
        log.info("github_issue_created", title=title, url=output)
        return True
    else:
        log.error("github_issue_failed", title=title)
        return False


def _ensure_labels_exist(labels: set[str]) -> None:
    """Create labels if they don't exist yet (errors are non-fatal)."""
    log = structlog.get_logger()
    label_colors = {
        "portfolio-review": "0E8A16",
        "high-priority": "D93F0B",
        "medium-priority": "FBCA04",
        "low-priority": "C5DEF5",
        "risk": "D93F0B",
        "performance": "1D76DB",
        "strategy": "5319E7",
        "config": "F9D0C4",
        "watchlist": "BFD4F2",
    }
    for label in labels:
        color = label_colors.get(label, "EDEDED")
        try:
            cmd = ["gh", "label", "create", label, "--color", color, "--force"]
            subprocess.run(  # noqa: S603, S607
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            log.warning("label_create_skipped", label=label)


def main() -> None:
    """Run the daily portfolio review and create GitHub issues."""
    config = AppConfig()
    setup_logging(config.log_level)
    log = structlog.get_logger()

    log.info("review_agent_started")

    broker = AlpacaBroker(config.broker)
    technical = TechnicalAnalyzer()
    reviewer = PortfolioReviewer(config.ai, config.trading)

    # Fetch portfolio
    portfolio = broker.get_portfolio_snapshot()
    log.info(
        "portfolio_loaded",
        equity=portfolio.equity,
        cash=portfolio.cash,
        positions=portfolio.position_count,
    )

    if portfolio.position_count == 0 and portfolio.equity < 1.0:
        log.info("empty_portfolio", message="No positions and no equity. Skipping review.")
        return

    # Compute technicals for all held + watchlist symbols
    technicals: dict[str, dict[str, float]] = {}
    hist_days = config.trading.historical_days

    crypto_watchlist = [s.strip() for s in config.trading.crypto_watchlist.split(",")]
    held_crypto = [_normalize_crypto_symbol(p.symbol) for p in portfolio.crypto_positions()]
    all_crypto = list(set(crypto_watchlist + held_crypto))

    if all_crypto:
        crypto_bars = broker.get_crypto_historical_bars(all_crypto, days=hist_days)
        crypto_technicals = technical.compute_indicators(crypto_bars)
        technicals.update(crypto_technicals)

    stock_watchlist = [s.strip() for s in config.trading.watchlist.split(",")]
    held_stocks = [p.symbol for p in portfolio.stock_positions()]
    all_stocks = list(set(stock_watchlist + held_stocks))

    if all_stocks:
        try:
            stock_bars = broker.get_historical_bars(all_stocks, days=hist_days)
            stock_technicals = technical.compute_indicators(stock_bars)
            technicals.update(stock_technicals)
        except Exception as e:
            log.warning("stock_data_fetch_failed", error=str(e))

    # Run the review
    review = reviewer.review(portfolio, technicals)

    grade = review.get("portfolio_grade", "?")
    summary = review.get("summary", "No summary available.")
    suggestions = review.get("suggestions", [])

    log.info("review_complete", grade=grade, suggestions=len(suggestions))

    # Create GitHub issues for each suggestion
    if not suggestions:
        log.info("no_suggestions", message="AI review produced no suggestions.")
        _write_github_output({"grade": grade, "summary": summary, "issues_created": 0})
        return

    # Close stale issues before creating new ones
    _close_stale_review_issues()

    # Check which categories/titles already have open issues to avoid duplicates
    existing_categories, existing_titles = _get_open_review_issues()

    # Ensure labels exist
    all_labels: set[str] = {"portfolio-review"}
    for s in suggestions:
        priority = s.get("priority", "medium")
        all_labels.add(f"{priority}-priority")
        category = s.get("category", "")
        if category:
            all_labels.add(category)
        for label in s.get("labels", []):
            all_labels.add(label)
    _ensure_labels_exist(all_labels)

    issues_created = 0
    skipped = 0
    for suggestion in suggestions:
        title = suggestion.get("title", "Portfolio improvement suggestion")
        priority = suggestion.get("priority", "medium")
        category = suggestion.get("category", "")
        body_text = suggestion.get("body", "")

        # Skip if an open issue already covers this category
        if category and category in existing_categories:
            log.info("issue_skipped_duplicate_category", title=title, category=category)
            skipped += 1
            continue

        # Skip if a similar title already exists (prevents repeated themes across categories)
        if _is_duplicate_title(title, existing_titles):
            log.info("issue_skipped_duplicate_title", title=title)
            skipped += 1
            continue

        # Build issue body with context
        issue_body = f"""## Portfolio Review — Grade: {grade}

{body_text}

---

**Priority:** {priority}
**Category:** {category}
**Portfolio Summary:** {summary}

<details>
<summary>Portfolio snapshot at time of review</summary>

- Equity: ${portfolio.equity:,.2f}
- Cash: ${portfolio.cash:,.2f}
- Positions: {portfolio.position_count}
- Unrealized P/L: ${portfolio.total_unrealized_pl:,.2f}

</details>

_This issue was automatically created by the portfolio review agent._
"""

        labels = ["portfolio-review", f"{priority}-priority"]
        if category:
            labels.append(category)
        for extra in suggestion.get("labels", []):
            if extra not in labels:
                labels.append(extra)

        if _create_github_issue(title, issue_body, labels):
            issues_created += 1
            # Track newly created category/title to avoid duplicates within same run
            if category:
                existing_categories.add(category)
            existing_titles.append(title.lower())

    log.info(
        "review_agent_complete",
        grade=grade,
        issues_created=issues_created,
        skipped=skipped,
    )

    _write_github_output(
        {
            "grade": grade,
            "summary": summary,
            "issues_created": issues_created,
        }
    )


def _normalize_crypto_symbol(symbol: str) -> str:
    """Normalize crypto symbols to the 'XXX/YYY' format required by the data API."""
    if "/" in symbol:
        return symbol
    if symbol.endswith("USD"):
        return symbol[:-3] + "/USD"
    return symbol


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
        log.error("review_agent_fatal_error", error=str(e), exc_info=True)
        sys.exit(1)
