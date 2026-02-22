"""Tests for persistent trade thesis storage."""

from __future__ import annotations

import tempfile

from financial_agent.persistence.thesis_store import ThesisStore, TradeThesis


def _make_thesis(**overrides) -> TradeThesis:
    defaults = {
        "symbol": "AAPL",
        "signal_type": "buy",
        "entry_price": 150.0,
        "entry_date": "2026-02-20",
        "reason": "Strong momentum breakout",
        "confidence": 0.8,
    }
    defaults.update(overrides)
    return TradeThesis(**defaults)


class TestThesisStore:
    def test_save_and_retrieve_thesis(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        thesis = _make_thesis()
        store.save_thesis(thesis)

        result = store.get_thesis("AAPL")
        assert result is not None
        assert result.symbol == "AAPL"
        assert result.entry_price == 150.0
        assert result.signal_type == "buy"
        assert result.reason == "Strong momentum breakout"

    def test_retrieve_nonexistent_returns_none(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        assert store.get_thesis("ZZZZZ") is None

    def test_save_overwrites_existing(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        store.save_thesis(_make_thesis(symbol="AAPL", reason="First reason"))
        store.save_thesis(_make_thesis(symbol="AAPL", reason="Updated reason"))

        result = store.get_thesis("AAPL")
        assert result is not None
        assert result.reason == "Updated reason"

    def test_persistence_across_instances(self):
        data_dir = tempfile.mkdtemp()
        store1 = ThesisStore(data_dir=data_dir)
        store1.save_thesis(_make_thesis(symbol="AAPL"))

        store2 = ThesisStore(data_dir=data_dir)
        result = store2.get_thesis("AAPL")
        assert result is not None
        assert result.symbol == "AAPL"


class TestGetActiveTheses:
    def test_filters_by_active_status(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        store.save_thesis(_make_thesis(symbol="AAPL", status="active"))
        store.save_thesis(_make_thesis(symbol="MSFT", status="closed"))
        store.save_thesis(_make_thesis(symbol="GOOGL", status="active"))

        active = store.get_active_theses()
        assert len(active) == 2
        assert "AAPL" in active
        assert "GOOGL" in active
        assert "MSFT" not in active

    def test_empty_store_returns_empty(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        assert store.get_active_theses() == {}


class TestCloseThesis:
    def test_close_changes_status(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        store.save_thesis(_make_thesis(symbol="AAPL"))
        store.close_thesis("AAPL", reason="Target reached")

        thesis = store.get_thesis("AAPL")
        assert thesis is not None
        assert thesis.status == "closed"

    def test_close_adds_note(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        store.save_thesis(_make_thesis(symbol="AAPL"))
        store.close_thesis("AAPL", reason="Hit target")

        thesis = store.get_thesis("AAPL")
        assert thesis is not None
        assert len(thesis.notes) == 1
        assert "CLOSED" in thesis.notes[0]
        assert "Hit target" in thesis.notes[0]

    def test_close_nonexistent_does_nothing(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        store.close_thesis("ZZZZZ")  # Should not raise

    def test_close_without_reason(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        store.save_thesis(_make_thesis(symbol="AAPL"))
        store.close_thesis("AAPL")

        thesis = store.get_thesis("AAPL")
        assert thesis is not None
        assert thesis.status == "closed"
        assert "CLOSED" in thesis.notes[0]


class TestInvalidateThesis:
    def test_invalidate_changes_status(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        store.save_thesis(_make_thesis(symbol="AAPL"))
        store.invalidate_thesis("AAPL", reason="Thesis broken")

        thesis = store.get_thesis("AAPL")
        assert thesis is not None
        assert thesis.status == "invalidated"

    def test_invalidate_adds_note(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        store.save_thesis(_make_thesis(symbol="AAPL"))
        store.invalidate_thesis("AAPL", reason="Support broken")

        thesis = store.get_thesis("AAPL")
        assert thesis is not None
        assert len(thesis.notes) == 1
        assert "INVALIDATED" in thesis.notes[0]
        assert "Support broken" in thesis.notes[0]

    def test_invalidate_nonexistent_does_nothing(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        store.invalidate_thesis("ZZZZZ")  # Should not raise


class TestAddNote:
    def test_appends_to_notes(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        store.save_thesis(_make_thesis(symbol="AAPL"))
        store.add_note("AAPL", "Price approaching target")
        store.add_note("AAPL", "Volume confirming breakout")

        thesis = store.get_thesis("AAPL")
        assert thesis is not None
        assert len(thesis.notes) == 2
        assert "Price approaching target" in thesis.notes[0]
        assert "Volume confirming breakout" in thesis.notes[1]

    def test_add_note_to_nonexistent_does_nothing(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        store.add_note("ZZZZZ", "This should be ignored")  # Should not raise


class TestFormatForPrompt:
    def test_no_theses_returns_default_message(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        result = store.format_for_prompt()
        assert result == "No active trade theses."

    def test_all_closed_returns_default_message(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        store.save_thesis(_make_thesis(symbol="AAPL"))
        store.close_thesis("AAPL")
        result = store.format_for_prompt()
        assert result == "No active trade theses."

    def test_with_active_theses(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        store.save_thesis(
            _make_thesis(
                symbol="AAPL",
                entry_price=150.0,
                target_price=180.0,
                stop_loss=140.0,
                confidence=0.8,
                invalidation="Drops below 200-day SMA",
            )
        )
        result = store.format_for_prompt()
        assert "Active Trade Theses" in result
        assert "AAPL" in result
        assert "$150.00" in result
        assert "Target: $180.00" in result
        assert "Stop Loss: $140.00" in result
        assert "80%" in result
        assert "Drops below 200-day SMA" in result

    def test_with_multiple_active_theses(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        store.save_thesis(_make_thesis(symbol="AAPL"))
        store.save_thesis(_make_thesis(symbol="MSFT", entry_price=350.0))
        result = store.format_for_prompt()
        assert "AAPL" in result
        assert "MSFT" in result

    def test_with_notes_shows_recent(self):
        data_dir = tempfile.mkdtemp()
        store = ThesisStore(data_dir=data_dir)
        store.save_thesis(_make_thesis(symbol="AAPL"))
        store.add_note("AAPL", "Note 1")
        store.add_note("AAPL", "Note 2")
        store.add_note("AAPL", "Note 3")
        store.add_note("AAPL", "Note 4")
        result = store.format_for_prompt()
        assert "Recent Notes" in result
        # Should show last 3 notes
        assert "Note 2" in result
        assert "Note 3" in result
        assert "Note 4" in result
