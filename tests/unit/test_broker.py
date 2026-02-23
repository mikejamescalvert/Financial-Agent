"""Tests for the Alpaca broker client and crypto symbol handling."""

from unittest.mock import MagicMock

from alpaca.trading.enums import TimeInForce

from financial_agent.broker.alpaca_client import AlpacaBroker
from financial_agent.main import _normalize_crypto_symbol
from financial_agent.portfolio.models import AssetClass, TradeOrder


def _make_broker():
    """Create an AlpacaBroker with mocked clients for testing."""
    broker = object.__new__(AlpacaBroker)
    broker._trading = MagicMock()
    broker._data = MagicMock()
    broker._crypto_data = MagicMock()
    return broker


class TestSubmitOrderTimeInForce:
    def test_stock_order_uses_day_tif(self):
        broker = _make_broker()
        order = TradeOrder(
            symbol="AAPL",
            side="buy",
            qty=1.0,
            reason="test",
            asset_class=AssetClass.US_EQUITY,
        )
        broker.submit_order(order, dry_run=False)
        call_args = broker._trading.submit_order.call_args
        request = call_args[0][0]
        assert request.time_in_force == TimeInForce.DAY

    def test_crypto_order_uses_gtc_tif(self):
        broker = _make_broker()
        order = TradeOrder(
            symbol="BTC/USD",
            side="buy",
            qty=0.01,
            reason="test",
            asset_class=AssetClass.CRYPTO,
        )
        broker.submit_order(order, dry_run=False)
        call_args = broker._trading.submit_order.call_args
        request = call_args[0][0]
        assert request.time_in_force == TimeInForce.GTC

    def test_dry_run_does_not_submit(self):
        broker = _make_broker()
        order = TradeOrder(
            symbol="BTC/USD",
            side="buy",
            qty=0.01,
            reason="test",
            asset_class=AssetClass.CRYPTO,
        )
        result = broker.submit_order(order, dry_run=True)
        assert result["status"] == "dry_run"
        broker._trading.submit_order.assert_not_called()

    def test_submission_error_returns_failed_status(self):
        broker = _make_broker()
        broker._trading.submit_order.side_effect = Exception("insufficient balance")
        order = TradeOrder(
            symbol="BTC/USD",
            side="sell",
            qty=0.01,
            reason="test",
            asset_class=AssetClass.CRYPTO,
        )
        result = broker.submit_order(order, dry_run=False)
        assert result["status"] == "failed"
        assert result["symbol"] == "BTC/USD"


class TestGetPositionsAssetClass:
    def test_crypto_position_detected(self):
        broker = _make_broker()
        mock_pos = MagicMock()
        mock_pos.symbol = "BTC/USD"
        mock_pos.qty = "0.5"
        mock_pos.avg_entry_price = "50000.0"
        mock_pos.current_price = "55000.0"
        mock_pos.market_value = "27500.0"
        mock_pos.unrealized_pl = "2500.0"
        mock_pos.unrealized_plpc = "0.10"
        mock_pos.side.value = "long"
        mock_pos.asset_class = "crypto"

        broker._trading.get_all_positions.return_value = [mock_pos]
        positions = broker.get_positions()
        assert len(positions) == 1
        assert positions[0].asset_class == AssetClass.CRYPTO

    def test_stock_position_detected(self):
        broker = _make_broker()
        mock_pos = MagicMock()
        mock_pos.symbol = "AAPL"
        mock_pos.qty = "10"
        mock_pos.avg_entry_price = "150.0"
        mock_pos.current_price = "160.0"
        mock_pos.market_value = "1600.0"
        mock_pos.unrealized_pl = "100.0"
        mock_pos.unrealized_plpc = "0.0667"
        mock_pos.side.value = "long"
        mock_pos.asset_class = "us_equity"

        broker._trading.get_all_positions.return_value = [mock_pos]
        positions = broker.get_positions()
        assert len(positions) == 1
        assert positions[0].asset_class == AssetClass.US_EQUITY


class TestNormalizeCryptoSymbol:
    def test_already_normalized(self):
        assert _normalize_crypto_symbol("BTC/USD") == "BTC/USD"

    def test_btcusd_normalized(self):
        assert _normalize_crypto_symbol("BTCUSD") == "BTC/USD"

    def test_ethusd_normalized(self):
        assert _normalize_crypto_symbol("ETHUSD") == "ETH/USD"

    def test_solusd_normalized(self):
        assert _normalize_crypto_symbol("SOLUSD") == "SOL/USD"

    def test_non_usd_passthrough(self):
        assert _normalize_crypto_symbol("BTCEUR") == "BTCEUR"
