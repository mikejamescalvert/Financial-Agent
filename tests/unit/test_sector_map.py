"""Tests for GICS sector mapping."""

from __future__ import annotations

from financial_agent.data.sector_map import SECTOR_MAP, get_sector, get_sector_symbols


class TestGetSector:
    def test_known_technology(self):
        assert get_sector("AAPL") == "Technology"
        assert get_sector("MSFT") == "Technology"
        assert get_sector("NVDA") == "Technology"

    def test_known_financials(self):
        assert get_sector("JPM") == "Financials"
        assert get_sector("V") == "Financials"
        assert get_sector("GS") == "Financials"

    def test_known_energy(self):
        assert get_sector("XOM") == "Energy"
        assert get_sector("CVX") == "Energy"

    def test_known_healthcare(self):
        assert get_sector("JNJ") == "Healthcare"
        assert get_sector("UNH") == "Healthcare"

    def test_known_consumer_discretionary(self):
        assert get_sector("AMZN") == "Consumer Discretionary"
        assert get_sector("TSLA") == "Consumer Discretionary"

    def test_known_industrials(self):
        assert get_sector("BA") == "Industrials"
        assert get_sector("CAT") == "Industrials"

    def test_known_utilities(self):
        assert get_sector("NEE") == "Utilities"

    def test_known_real_estate(self):
        assert get_sector("AMT") == "Real Estate"

    def test_known_materials(self):
        assert get_sector("LIN") == "Materials"

    def test_known_consumer_staples(self):
        assert get_sector("PG") == "Consumer Staples"
        assert get_sector("KO") == "Consumer Staples"

    def test_known_communication_services(self):
        assert get_sector("DIS") == "Communication Services"

    def test_unknown_symbol_returns_unknown(self):
        assert get_sector("ZZZZZ") == "Unknown"
        assert get_sector("") == "Unknown"
        assert get_sector("BTC/USD") == "Unknown"


class TestGetSectorSymbols:
    def test_technology_symbols(self):
        tech_symbols = get_sector_symbols("Technology")
        assert "AAPL" in tech_symbols
        assert "MSFT" in tech_symbols
        assert "NVDA" in tech_symbols
        assert len(tech_symbols) == 15

    def test_financials_symbols(self):
        fin_symbols = get_sector_symbols("Financials")
        assert "JPM" in fin_symbols
        assert "V" in fin_symbols
        assert len(fin_symbols) == 10

    def test_energy_symbols(self):
        energy_symbols = get_sector_symbols("Energy")
        assert "XOM" in energy_symbols
        assert "CVX" in energy_symbols
        assert len(energy_symbols) == 8

    def test_unknown_sector_returns_empty(self):
        assert get_sector_symbols("Nonexistent") == []

    def test_empty_sector_returns_empty(self):
        assert get_sector_symbols("") == []


class TestSectorMap:
    def test_contains_all_expected_sectors(self):
        sectors = set(SECTOR_MAP.values())
        expected = {
            "Technology",
            "Consumer Discretionary",
            "Financials",
            "Healthcare",
            "Industrials",
            "Communication Services",
            "Energy",
            "Utilities",
            "Real Estate",
            "Materials",
            "Consumer Staples",
        }
        assert sectors == expected

    def test_map_is_not_empty(self):
        assert len(SECTOR_MAP) > 0

    def test_all_values_are_strings(self):
        for symbol, sector in SECTOR_MAP.items():
            assert isinstance(symbol, str)
            assert isinstance(sector, str)
            assert len(symbol) > 0
            assert len(sector) > 0
