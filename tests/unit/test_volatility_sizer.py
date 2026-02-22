"""Tests for volatility-based position sizing."""

from __future__ import annotations

from financial_agent.risk.volatility import VolatilitySizer


class TestClassifyVolatility:
    def test_low_volatility(self):
        sizer = VolatilitySizer()
        assert sizer.classify_volatility(0.5) == "low"
        assert sizer.classify_volatility(0.0) == "low"
        assert sizer.classify_volatility(0.99) == "low"

    def test_medium_volatility(self):
        sizer = VolatilitySizer()
        assert sizer.classify_volatility(1.0) == "medium"
        assert sizer.classify_volatility(2.0) == "medium"
        assert sizer.classify_volatility(3.0) == "medium"

    def test_high_volatility(self):
        sizer = VolatilitySizer()
        assert sizer.classify_volatility(3.1) == "high"
        assert sizer.classify_volatility(4.0) == "high"
        assert sizer.classify_volatility(5.0) == "high"

    def test_very_high_volatility(self):
        sizer = VolatilitySizer()
        assert sizer.classify_volatility(5.1) == "very_high"
        assert sizer.classify_volatility(10.0) == "very_high"
        assert sizer.classify_volatility(100.0) == "very_high"


class TestMaxPositionPct:
    def test_low_vol_cap(self):
        sizer = VolatilitySizer()
        # low volatility (atr_pct < 1.0) -> 0.12
        assert sizer.max_position_pct(0.5) == 0.12

    def test_medium_vol_cap(self):
        sizer = VolatilitySizer()
        # medium volatility (1.0 <= atr_pct <= 3.0) -> 0.08
        assert sizer.max_position_pct(2.0) == 0.08

    def test_high_vol_cap(self):
        sizer = VolatilitySizer()
        # high volatility (3.0 < atr_pct <= 5.0) -> 0.05
        assert sizer.max_position_pct(4.0) == 0.05

    def test_very_high_vol_cap(self):
        sizer = VolatilitySizer()
        # very high volatility (atr_pct > 5.0) -> 0.03
        assert sizer.max_position_pct(8.0) == 0.03

    def test_custom_caps(self):
        custom_caps = {
            "low": 0.20,
            "medium": 0.15,
            "high": 0.10,
            "very_high": 0.05,
        }
        sizer = VolatilitySizer(volatility_caps=custom_caps)
        assert sizer.max_position_pct(0.5) == 0.20
        assert sizer.max_position_pct(2.0) == 0.15


class TestSizePosition:
    def test_basic_sizing(self):
        sizer = VolatilitySizer(risk_budget_pct=0.02)
        # equity=100000, price=100, atr=2
        # risk_amount = 100000 * 0.02 = 2000
        # qty = 2000 / 2 = 1000
        # atr_pct = (2/100)*100 = 2.0 -> medium -> cap = 0.08
        # max_value = 0.08 * 100000 = 8000
        # position_value = 1000 * 100 = 100000 > 8000, so cap
        # qty = 8000 / 100 = 80
        qty = sizer.size_position(equity=100_000.0, price=100.0, atr=2.0)
        assert qty == 80.0

    def test_sizing_not_capped(self):
        sizer = VolatilitySizer(risk_budget_pct=0.002)
        # risk_amount = 100000 * 0.002 = 200
        # qty = 200 / 5 = 40
        # atr_pct = (5/100)*100 = 5.0 -> high -> cap = 0.05
        # max_value = 0.05 * 100000 = 5000
        # position_value = 40 * 100 = 4000 < 5000, no cap
        qty = sizer.size_position(equity=100_000.0, price=100.0, atr=5.0)
        assert qty == 40.0

    def test_respects_max_cap(self):
        sizer = VolatilitySizer(risk_budget_pct=0.10)
        # risk_amount = 100000 * 0.10 = 10000
        # qty = 10000 / 1 = 10000
        # atr_pct = (1/100)*100 = 1.0 -> medium -> cap = 0.08
        # max_value = 0.08 * 100000 = 8000
        # position_value = 10000 * 100 = 1,000,000 > 8000
        # qty = 8000 / 100 = 80
        qty = sizer.size_position(equity=100_000.0, price=100.0, atr=1.0)
        assert qty == 80.0

    def test_zero_atr_returns_zero(self):
        sizer = VolatilitySizer()
        assert sizer.size_position(equity=100_000.0, price=100.0, atr=0.0) == 0.0

    def test_zero_price_returns_zero(self):
        sizer = VolatilitySizer()
        assert sizer.size_position(equity=100_000.0, price=0.0, atr=2.0) == 0.0

    def test_zero_equity_returns_zero(self):
        sizer = VolatilitySizer()
        assert sizer.size_position(equity=0.0, price=100.0, atr=2.0) == 0.0

    def test_negative_atr_returns_zero(self):
        sizer = VolatilitySizer()
        assert sizer.size_position(equity=100_000.0, price=100.0, atr=-1.0) == 0.0

    def test_result_is_rounded(self):
        sizer = VolatilitySizer(risk_budget_pct=0.02)
        qty = sizer.size_position(equity=100_000.0, price=33.0, atr=3.0)
        # Check it's rounded to 2 decimals
        assert qty == round(qty, 2)


class TestGetSizingContext:
    def test_with_valid_technicals(self):
        sizer = VolatilitySizer()
        technicals = {
            "AAPL": {"atr_14": 3.0, "current_price": 150.0},
            "MSFT": {"atr_14": 5.0, "current_price": 300.0},
        }
        context = sizer.get_sizing_context(technicals)
        assert "AAPL" in context
        assert "MSFT" in context
        assert "atr_pct" in context["AAPL"]
        assert "vol_tier_numeric" in context["AAPL"]
        assert "max_position_pct" in context["AAPL"]

    def test_skips_missing_atr(self):
        sizer = VolatilitySizer()
        technicals = {
            "AAPL": {"current_price": 150.0},  # Missing atr_14
        }
        context = sizer.get_sizing_context(technicals)
        assert "AAPL" not in context

    def test_skips_missing_price(self):
        sizer = VolatilitySizer()
        technicals = {
            "AAPL": {"atr_14": 3.0},  # Missing current_price
        }
        context = sizer.get_sizing_context(technicals)
        assert "AAPL" not in context

    def test_skips_zero_price(self):
        sizer = VolatilitySizer()
        technicals = {
            "AAPL": {"atr_14": 3.0, "current_price": 0.0},
        }
        context = sizer.get_sizing_context(technicals)
        assert "AAPL" not in context

    def test_atr_pct_calculation(self):
        sizer = VolatilitySizer()
        technicals = {
            "AAPL": {"atr_14": 3.0, "current_price": 150.0},
        }
        context = sizer.get_sizing_context(technicals)
        expected_atr_pct = round((3.0 / 150.0) * 100, 4)
        assert context["AAPL"]["atr_pct"] == expected_atr_pct

    def test_vol_tier_numeric_values(self):
        sizer = VolatilitySizer()
        technicals = {
            "LOW": {"atr_14": 0.5, "current_price": 100.0},  # atr_pct=0.5 -> low -> 0.0
            "MED": {"atr_14": 2.0, "current_price": 100.0},  # atr_pct=2.0 -> medium -> 1.0
            "HIGH": {"atr_14": 4.0, "current_price": 100.0},  # atr_pct=4.0 -> high -> 2.0
            "VHIGH": {"atr_14": 8.0, "current_price": 100.0},  # atr_pct=8.0 -> very_high -> 3.0
        }
        context = sizer.get_sizing_context(technicals)
        assert context["LOW"]["vol_tier_numeric"] == 0.0
        assert context["MED"]["vol_tier_numeric"] == 1.0
        assert context["HIGH"]["vol_tier_numeric"] == 2.0
        assert context["VHIGH"]["vol_tier_numeric"] == 3.0

    def test_empty_technicals(self):
        sizer = VolatilitySizer()
        context = sizer.get_sizing_context({})
        assert context == {}
