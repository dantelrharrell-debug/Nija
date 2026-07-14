from __future__ import annotations

import importlib.util
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "kraken_synthetic_equity_scrub_under_test",
        BOT_DIR / "kraken_synthetic_equity_position_scrub_patch.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scrub_mapping_removes_only_synthetic_cache_metadata():
    module = _load()
    cleaned, removed = module._scrub_mapping(
        {
            "ZUSD": "100.00",
            "SOL": "1.25",
            "AIR": "2901.0",
            "CANONICAL_EQUITY": 230.32,
            "TOTAL_FUNDS": 230.32,
            "EQUITY": 230.32,
            "CRYPTO_USD": 30.32,
            "result": {
                "ETH": "0.5",
                "HELD_EXCLUDED_FROM_EQUITY_SUM": True,
            },
        }
    )

    assert cleaned["ZUSD"] == "100.00"
    assert cleaned["SOL"] == "1.25"
    assert cleaned["AIR"] == "2901.0"
    assert cleaned["TOTAL_FUNDS"] == 230.32
    assert cleaned["EQUITY"] == 230.32
    assert cleaned["CRYPTO_USD"] == 30.32
    assert cleaned["result"]["ETH"] == "0.5"
    assert "CANONICAL_EQUITY" not in cleaned
    assert "CANONICAL_EQUITY" in removed
    assert "result.HELD_EXCLUDED_FROM_EQUITY_SUM" in removed


def test_filter_rows_removes_accounting_fields_when_presented_as_positions():
    module = _load()
    rows = [
        {"symbol": "CANONICAL_EQUITY-USD", "quantity": 230.32},
        {"symbol": "TOTAL_FUNDS-USD", "quantity": 230.32},
        {"symbol": "EQUITY-USD", "quantity": 230.32},
        {"symbol": "SOL-USD", "quantity": 1.0},
        {"symbol": "XDC-USD", "quantity": 72.8198},
    ]

    filtered = module._filter_rows(rows)
    assert [row["symbol"] for row in filtered] == ["SOL-USD", "XDC-USD"]


def test_real_kraken_assets_are_not_metadata():
    module = _load()
    for symbol in ("SOL", "ETH", "AIR", "XDC", "TNSR", "MOVR", "ORCA", "1INCH"):
        assert module._metadata_name(symbol) is False
        assert module._cache_metadata_name(symbol) is False
