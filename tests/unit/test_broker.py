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


class TestPendingOrderManagement:
    def test_get_pending_orders_returns_open_orders(self):
        broker = _make_broker()
        mock_order = MagicMock()
        mock_order.id = "order-123"
        mock_order.symbol = "AAPL"
        mock_order.side = "buy"
        mock_order.qty = "5"
        mock_order.type = "limit"
        mock_order.status = "new"
        broker._trading.get_orders.return_value = [mock_order]

        orders = broker.get_pending_orders("AAPL")
        assert len(orders) == 1
        assert orders[0]["id"] == "order-123"
        assert orders[0]["symbol"] == "AAPL"

    def test_get_pending_orders_handles_exception(self):
        broker = _make_broker()
        broker._trading.get_orders.side_effect = Exception("API error")
        orders = broker.get_pending_orders("AAPL")
        assert orders == []

    def test_cancel_pending_orders_cancels_all(self):
        broker = _make_broker()
        mock_order1 = MagicMock()
        mock_order1.id = "order-1"
        mock_order1.symbol = "XOM"
        mock_order1.side = "buy"
        mock_order1.qty = "0.12"
        mock_order1.type = "limit"
        mock_order1.status = "new"
        mock_order2 = MagicMock()
        mock_order2.id = "order-2"
        mock_order2.symbol = "XOM"
        mock_order2.side = "buy"
        mock_order2.qty = "0.11"
        mock_order2.type = "limit"
        mock_order2.status = "new"
        broker._trading.get_orders.return_value = [mock_order1, mock_order2]

        cancelled = broker.cancel_pending_orders("XOM")
        assert cancelled == 2
        assert broker._trading.cancel_order_by_id.call_count == 2

    def test_cancel_pending_orders_handles_partial_failure(self):
        broker = _make_broker()
        mock_order = MagicMock()
        mock_order.id = "order-1"
        mock_order.symbol = "AAPL"
        mock_order.side = "buy"
        mock_order.qty = "1"
        mock_order.type = "limit"
        mock_order.status = "new"
        broker._trading.get_orders.return_value = [mock_order]
        broker._trading.cancel_order_by_id.side_effect = Exception("already filled")

        cancelled = broker.cancel_pending_orders("AAPL")
        assert cancelled == 0

    def test_cancel_pending_orders_with_no_pending(self):
        broker = _make_broker()
        broker._trading.get_orders.return_value = []
        cancelled = broker.cancel_pending_orders("AAPL")
        assert cancelled == 0


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
