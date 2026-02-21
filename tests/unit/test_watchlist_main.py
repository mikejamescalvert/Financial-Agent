"""Tests for the watchlist_main entry point helper functions."""

from unittest.mock import patch

from financial_agent.watchlist_main import _run_gh_command, _update_github_variable


class TestRunGhCommand:
    """Test the gh CLI wrapper."""

    @patch("financial_agent.watchlist_main.subprocess.run")
    def test_successful_command(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "success output\n"
        mock_run.return_value.stderr = ""

        success, output = _run_gh_command(["gh", "variable", "set", "FOO", "--body", "bar"])

        assert success is True
        assert output == "success output"

    @patch("financial_agent.watchlist_main.subprocess.run")
    def test_failed_command(self, mock_run):
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "permission denied"

        success, output = _run_gh_command(["gh", "variable", "set", "FOO", "--body", "bar"])

        assert success is False
        assert "permission denied" in output

    @patch("financial_agent.watchlist_main.subprocess.run")
    def test_timeout(self, mock_run):
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh", timeout=30)

        success, output = _run_gh_command(["gh", "variable", "set", "FOO"])

        assert success is False

    @patch("financial_agent.watchlist_main.subprocess.run")
    def test_gh_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("gh not found")

        success, output = _run_gh_command(["gh", "variable", "set", "FOO"])

        assert success is False


class TestUpdateGithubVariable:
    """Test GitHub variable update logic."""

    @patch("financial_agent.watchlist_main._run_gh_command")
    def test_successful_update(self, mock_gh):
        mock_gh.return_value = (True, "")

        result = _update_github_variable("TRADING_WATCHLIST", "AAPL,MSFT,NVDA")

        assert result is True
        mock_gh.assert_called_once_with(
            ["gh", "variable", "set", "TRADING_WATCHLIST", "--body", "AAPL,MSFT,NVDA"]
        )

    @patch("financial_agent.watchlist_main._run_gh_command")
    def test_failed_update(self, mock_gh):
        mock_gh.return_value = (False, "error")

        result = _update_github_variable("TRADING_WATCHLIST", "AAPL")

        assert result is False
