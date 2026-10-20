from bot.pretrade_attestation_validation_v452 import REQUIRED, evaluate_pretrade_certificate


def valid(now=1000.0):
    return {name: {"verified": True, "source": "authenticated_broker",
                   "observed_at_epoch": now} for name in REQUIRED}


def test_complete_current_certificate_never_authorizes():
    result = evaluate_pretrade_certificate(valid(), now_epoch=1000)
    assert result["certified"] is True
    assert result["authorizes_orders"] is False
    assert result["post_trade_confirmation_required"] is True


def test_each_missing_attestation_denies():
    for name in REQUIRED:
        rows = valid()
        del rows[name]
        result = evaluate_pretrade_certificate(rows, now_epoch=1000)
        assert result["certified"] is False
        assert name in result["missing"]


def test_stale_untrusted_or_string_true_denies():
    rows = valid()
    rows["protective_exit_readback"]["observed_at_epoch"] = 1
    assert not evaluate_pretrade_certificate(rows, now_epoch=1000)["certified"]
    rows = valid()
    rows["kill_switch_clear"]["verified"] = "true"
    assert not evaluate_pretrade_certificate(rows, now_epoch=1000)["certified"]
    rows = valid()
    rows["account_identity"]["source"] = "self_reported"
    assert not evaluate_pretrade_certificate(rows, now_epoch=1000)["certified"]
