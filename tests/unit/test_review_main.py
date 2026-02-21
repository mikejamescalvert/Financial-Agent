"""Tests for the review_main entry point helper functions."""

from unittest.mock import patch

from financial_agent.review_main import _create_github_issue


class TestCreateGitHubIssue:
    """Test GitHub issue creation via gh CLI."""

    @patch("financial_agent.review_main.subprocess.run")
    def test_successful_issue_creation(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "https://github.com/owner/repo/issues/1\n"
        mock_run.return_value.stderr = ""

        result = _create_github_issue(
            title="Test issue",
            body="Test body",
            labels=["portfolio-review", "high-priority"],
        )

        assert result is True
        args = mock_run.call_args[0][0]
        assert "gh" in args
        assert "issue" in args
        assert "create" in args
        assert "--title" in args
        assert "Test issue" in args
        assert "--label" in args

    @patch("financial_agent.review_main.subprocess.run")
    def test_failed_issue_creation(self, mock_run):
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "Not authenticated"

        result = _create_github_issue(
            title="Test issue",
            body="Test body",
            labels=["portfolio-review"],
        )

        assert result is False

    @patch("financial_agent.review_main.subprocess.run")
    def test_issue_creation_timeout(self, mock_run):
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh", timeout=30)

        result = _create_github_issue(
            title="Test issue",
            body="Test body",
            labels=[],
        )

        assert result is False

    @patch("financial_agent.review_main.subprocess.run")
    def test_gh_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("gh not found")

        result = _create_github_issue(
            title="Test issue",
            body="Test body",
            labels=[],
        )

        assert result is False
