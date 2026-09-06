from __future__ import annotations

import pytest

from bot import runtime_kraken_margin_full_protection_v371_patch as v371


@pytest.fixture(autouse=True)
def _policy_env(monkeypatch):
    monkeypatch.setenv("NIJA_HARD_STOP_LOSS_PCT", "0.015")
    monkeypatch.setenv("NIJA_MAX_POSITION_LOSS_USD", "2.00")
    monkeypatch.setenv("NIJA_PROFIT_TARGET_TP1_PCT", "0.005")
    monkeypatch.setenv("NIJA_PROFIT_TARGET_TP2_PCT", "0.010")
    monkeypatch.setenv("NIJA_PROFIT_TARGET_TP3_PCT", "0.020")
    monkeypatch.setenv("NIJA_TRAILING_STOP_ENABLED", "true")
    monkeypatch.setenv("NIJA_TRAILING_STOP_ACTIVATION_PCT", "0.008")
    monkeypatch.setenv("NIJA_TRAILING_STOP_PCT", "0.0035")
    monkeypatch.setenv("NIJA_TRAILING_TP_ENABLED", "true")
    monkeypatch.setenv("NIJA_TRAILING_TP_ACTIVATION_PCT", "0.008")
    monkeypatch.setenv("NIJA_TRAILING_TP_CALLBACK_PCT", "0.0035")


def _margin_row(**overrides):
    row = {
        "account": "platform:kraken",
        "broker": "kraken",
        "symbol": "ETH-USD",
        "quantity": 0.13742703,
        "qty": 0.13742703,
        "entry_price": 2498.6764976293243,
        "cost_basis_usd": 343.38569,
        "side": "long",
        "margin_position": True,
        "kraken_margin_openpositions": True,
        "position_ids": ("POS1", "POS2", "POS3", "POS4", "POS5", "POS6"),
        "native_stop_loss_verified": False,
        "native_take_profit_verified": False,
        "software_exit_monitor_verified": True,
    }
    row.update(overrides)
    return row


def test_margin_row_receives_fixed_and_trailing_policy():
    row = v371._ensure_software_targets(_margin_row())

    stop_pct = 2.0 / 343.38569
    entry = 2498.6764976293243
    assert row["stop_loss"] == pytest.approx(entry * (1.0 - stop_pct))
    assert row["take_profit_1"] == pytest.approx(entry * 1.005)
    assert row["take_profit_2"] == pytest.approx(entry * 1.010)
    assert row["take_profit_3"] == pytest.approx(entry * 1.020)
    assert row["software_stop_loss_available"] is True
    assert row["software_take_profit_available"] is True
    assert row["software_trailing_stop_available"] is True
    assert row["software_trailing_take_profit_available"] is True
    assert row["trailing_stop_activation_pct"] == pytest.approx(0.008)
    assert row["trailing_stop_distance_pct"] == pytest.approx(0.0035)
    assert row["trailing_take_profit_activation_pct"] == pytest.approx(0.008)
    assert row["trailing_take_profit_callback_pct"] == pytest.approx(0.0035)
    assert row["software_protection_identity_verified"] is True
    assert row["software_protection_targets_complete"] is True
    assert row["protection_position_ids"] == ("POS1", "POS2", "POS3", "POS4", "POS5", "POS6")


def test_native_stop_only_never_certifies_four_way_margin_protection(monkeypatch):
    import bot.runtime_kraken_margin_canonical_coverage_v366_patch as v366

    original = v366.margin_coverage_rows

    def base(_account, _broker):
        return [_margin_row(
            native_stop_loss_verified=True,
            native_take_profit_verified=False,
            software_exit_monitor_verified=False,
        )], []

    monkeypatch.setattr(v366, "margin_coverage_rows", base)
    assert v371._patch_margin_coverage_truth() is True
    rows, reasons = v366.margin_coverage_rows("platform:kraken", object())

    assert rows[0]["protective_stop_verified"] is True
    assert rows[0]["protective_take_profit_verified"] is False
    assert rows[0]["protective_trailing_stop_verified"] is False
    assert rows[0]["protective_trailing_take_profit_verified"] is False
    assert rows[0]["protective_exit_verified"] is False
    assert rows[0]["protective_exit_mode"] == "unverified"
    assert "kraken_margin_take_profit_unverified:ETH-USD" in reasons
    assert "kraken_margin_trailing_stop_unverified:ETH-USD" in reasons
    assert "kraken_margin_trailing_take_profit_unverified:ETH-USD" in reasons
    monkeypatch.setattr(v366, "margin_coverage_rows", original)


def test_software_monitor_with_exact_position_and_all_four_is_verified(monkeypatch):
    import bot.runtime_kraken_margin_canonical_coverage_v366_patch as v366

    original = v366.margin_coverage_rows

    def base(_account, _broker):
        return [_margin_row()], ["kraken_margin_protective_exit_unverified:ETH-USD"]

    monkeypatch.setattr(v366, "margin_coverage_rows", base)
    assert v371._patch_margin_coverage_truth() is True
    rows, reasons = v366.margin_coverage_rows("platform:kraken", object())
    row = rows[0]

    assert row["software_stop_loss_verified"] is True
    assert row["software_take_profit_verified"] is True
    assert row["software_trailing_stop_verified"] is True
    assert row["software_trailing_take_profit_verified"] is True
    assert row["protective_position_identity_verified"] is True
    assert row["protective_stop_verified"] is True
    assert row["protective_take_profit_verified"] is True
    assert row["protective_trailing_stop_verified"] is True
    assert row["protective_trailing_take_profit_verified"] is True
    assert row["protective_exit_verified"] is True
    assert row["protective_exit_mode"] == "software_margin_monitor_four_way"
    assert "kraken_margin_software_stop_loss" in row["exit_protections_attached"]
    assert "kraken_margin_software_take_profit" in row["exit_protections_attached"]
    assert "kraken_margin_software_trailing_stop_loss" in row["exit_protections_attached"]
    assert "kraken_margin_software_trailing_take_profit" in row["exit_protections_attached"]
    assert "kraken_margin_software_exit_monitor" in row["exit_protections_attached"]
    assert "kraken_margin_protective_exit_unverified:ETH-USD" not in reasons
    monkeypatch.setattr(v366, "margin_coverage_rows", original)


def test_disabling_one_trailing_leg_fails_closed(monkeypatch):
    import bot.runtime_kraken_margin_canonical_coverage_v366_patch as v366

    monkeypatch.setenv("NIJA_TRAILING_TP_ENABLED", "false")
    original = v366.margin_coverage_rows

    def base(_account, _broker):
        return [_margin_row()], []

    monkeypatch.setattr(v366, "margin_coverage_rows", base)
    assert v371._patch_margin_coverage_truth() is True
    rows, reasons = v366.margin_coverage_rows("platform:kraken", object())
    row = rows[0]

    assert row["protective_trailing_stop_verified"] is True
    assert row["protective_trailing_take_profit_verified"] is False
    assert row["protective_exit_verified"] is False
    assert "kraken_margin_trailing_take_profit_unverified:ETH-USD" in reasons
    monkeypatch.setattr(v366, "margin_coverage_rows", original)


def test_software_monitor_without_authenticated_position_ids_fails_closed(monkeypatch):
    import bot.runtime_kraken_margin_canonical_coverage_v366_patch as v366

    original = v366.margin_coverage_rows

    def base(_account, _broker):
        return [_margin_row(position_ids=(), position_id="")], []

    monkeypatch.setattr(v366, "margin_coverage_rows", base)
    assert v371._patch_margin_coverage_truth() is True
    rows, reasons = v366.margin_coverage_rows("platform:kraken", object())
    row = rows[0]

    assert row["protective_position_identity_verified"] is False
    assert row["software_stop_loss_verified"] is False
    assert row["software_take_profit_verified"] is False
    assert row["software_trailing_stop_verified"] is False
    assert row["software_trailing_take_profit_verified"] is False
    assert row["protective_exit_verified"] is False
    assert "kraken_margin_position_identity_unverified:ETH-USD" in reasons
    monkeypatch.setattr(v366, "margin_coverage_rows", original)


def test_native_fixed_only_does_not_certify_trailing_protection(monkeypatch):
    import bot.runtime_kraken_margin_canonical_coverage_v366_patch as v366

    original = v366.margin_coverage_rows

    def base(_account, _broker):
        return [_margin_row(
            native_stop_loss_verified=True,
            native_take_profit_verified=True,
            software_exit_monitor_verified=False,
        )], []

    monkeypatch.setattr(v366, "margin_coverage_rows", base)
    assert v371._patch_margin_coverage_truth() is True
    rows, reasons = v366.margin_coverage_rows("platform:kraken", object())
    row = rows[0]

    assert row["protective_stop_verified"] is True
    assert row["protective_take_profit_verified"] is True
    assert row["protective_trailing_stop_verified"] is False
    assert row["protective_trailing_take_profit_verified"] is False
    assert row["protective_exit_verified"] is False
    assert "kraken_margin_trailing_stop_unverified:ETH-USD" in reasons
    assert "kraken_margin_trailing_take_profit_unverified:ETH-USD" in reasons
    monkeypatch.setattr(v366, "margin_coverage_rows", original)


def test_native_fixed_plus_software_trailing_monitor_is_hybrid(monkeypatch):
    import bot.runtime_kraken_margin_canonical_coverage_v366_patch as v366

    original = v366.margin_coverage_rows

    def base(_account, _broker):
        return [_margin_row(
            native_stop_loss_verified=True,
            native_take_profit_verified=True,
            software_exit_monitor_verified=True,
        )], []

    monkeypatch.setattr(v366, "margin_coverage_rows", base)
    assert v371._patch_margin_coverage_truth() is True
    rows, reasons = v366.margin_coverage_rows("platform:kraken", object())
    row = rows[0]

    assert row["protective_stop_verified"] is True
    assert row["protective_take_profit_verified"] is True
    assert row["protective_trailing_stop_verified"] is True
    assert row["protective_trailing_take_profit_verified"] is True
    assert row["protective_exit_verified"] is True
    assert row["protective_exit_mode"] == "hybrid_native_fixed_software_trailing"
    assert "native_stop_loss" in row["exit_protections_attached"]
    assert "native_take_profit" in row["exit_protections_attached"]
    assert "kraken_margin_software_trailing_stop_loss" in row["exit_protections_attached"]
    assert "kraken_margin_software_trailing_take_profit" in row["exit_protections_attached"]
    assert reasons == []
    monkeypatch.setattr(v366, "margin_coverage_rows", original)
