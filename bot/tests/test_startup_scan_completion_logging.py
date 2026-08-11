from __future__ import annotations

from pathlib import Path


def test_first_market_scan_and_completion_use_distinct_latches() -> None:
    source = (
        Path(__file__).resolve().parents[2] / "bot" / "nija_core_loop.py"
    ).read_text(encoding="utf-8")

    assert "if not self._first_scan_started_logged:" in source
    assert 'logger.critical(\n                "FIRST_MARKET_SCAN symbols_scanned=%d markets_loaded=%d",' in source
    assert "if not self._first_scan_completed_logged:" in source
    assert '"FIRST_SCAN_COMPLETED symbols_scanned=%d markets_loaded=%d "' in source
