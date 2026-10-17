from bot.preflight_observability import REQUIRED_PREFLIGHT, observe_preflight


def ready():
    return dict.fromkeys(REQUIRED_PREFLIGHT, True)


def test_no_fill_can_pass_preflight_without_authorizing():
    report = observe_preflight(ready(), {})
    assert report["preflight_operational_ready"] is True
    assert report["last_execution_evidence_status"] == "unknown"
    assert report["activation_allowed"] is False


def test_missing_protective_exit_fails_closed():
    values = ready()
    values["protective_exits_verified"] = False
    report = observe_preflight(values, {"verified": True})
    assert report["preflight_operational_ready"] is False
    assert "protective_exits_verified" in report["preflight_missing_attestations"]


def test_unknown_ledger_and_active_kill_switch_block():
    values = ready()
    values.pop("kraken_ledger_reconciled")
    values["kill_switch_clear"] = False
    report = observe_preflight(values)
    assert set(["kraken_ledger_reconciled", "kill_switch_clear"]).issubset(
        report["preflight_missing_attestations"])
    assert report["activation_allowed"] is False


def test_non_boolean_truthy_values_are_not_accepted():
    values = ready()
    values["capital_fresh"] = "true"
    assert observe_preflight(values)["preflight_operational_ready"] is False
