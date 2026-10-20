from bot.startup_transition_candidate_v454 import evaluate_startup_transition

REQUIRED = ("writer_fenced", "nonce_current", "kill_switch_clear",
            "capital_current", "positions_reconciled",
            "protective_exits_confirmed", "ledger_certified",
            "broker_account_authenticated", "duplicate_order_fence",
            "operator_approved")


def test_complete_candidate_still_cannot_authorize_orders():
    result = evaluate_startup_transition(
        {"certified": True}, {name: True for name in REQUIRED}
    )
    assert result["pretrade_transition_candidate"] is True
    assert result["execution_authority"] is False
    assert result["allow_new_orders"] is False


def test_every_missing_safety_gate_prevents_candidate():
    for name in REQUIRED:
        controls = {field: True for field in REQUIRED}
        controls[name] = False
        result = evaluate_startup_transition({"certified": True}, controls)
        assert result["pretrade_transition_candidate"] is False
        assert name in result["missing"]


def test_certificate_missing_denies():
    result = evaluate_startup_transition(
        {"certified": False}, {name: True for name in REQUIRED}
    )
    assert result["allow_new_orders"] is False
    assert "independent_pretrade_certificate" in result["missing"]
