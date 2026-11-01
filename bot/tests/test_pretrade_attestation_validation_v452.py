"""Account-bound, non-authorizing independent evidence regressions."""
from bot.pretrade_attestation_validation_v452 import (
    REQUIRED, SOURCES, PROOF_BY_SOURCE, evaluate_pretrade_certificate,
)

ACCOUNT = "platform:kraken"
TRUSTED = {field: "trusted-" + field for field in REQUIRED}


def valid(now=1000.0):
    return {
        field: {
            "account": ACCOUNT, "verified": True, "read_only": True,
            "scope_verified": True, "source": SOURCES[field],
            "provider_id": TRUSTED[field], "evidence_id": "read-" + field,
            "observed_at_epoch": now,
            "provenance": {
                "account_scope_verified": True,
                "collector_identity_verified": True,
                "snapshot_complete": True,
                "complete_pagination_verified": True,
                PROOF_BY_SOURCE[SOURCES[field]]: True,
            },
        }
        for field in REQUIRED
    }


def check(rows=None, **kwargs):
    return evaluate_pretrade_certificate(
        valid() if rows is None else rows,
        account=ACCOUNT, trusted_provider_ids=TRUSTED, now_epoch=1000,
        **kwargs,
    )


def test_complete_current_certificate_is_diagnostic_only():
    result = check()
    assert result["certified"] is True
    assert result["authorizes_orders"] is False
    assert result["post_trade_confirmation_required"] is True


def test_missing_account_or_registry_fails_closed():
    assert not evaluate_pretrade_certificate(valid(), now_epoch=1000)["certified"]
    assert not evaluate_pretrade_certificate(
        valid(), account=ACCOUNT, now_epoch=1000,
    )["certified"]


def test_each_missing_attestation_denies():
    for name in REQUIRED:
        rows = valid()
        del rows[name]
        result = check(rows)
        assert not result["certified"]
        assert name in result["missing"]


def test_stale_future_untrusted_or_string_true_denies():
    for name, key, value in (
        ("protective_exit_readback", "observed_at_epoch", 1),
        ("protective_exit_readback", "observed_at_epoch", 1001),
        ("kill_switch_clear", "verified", "true"),
        ("account_identity", "source", "self_reported"),
        ("broker_balances", "account", "user:other:kraken"),
        ("broker_balances", "provider_id", "untrusted"),
        ("broker_balances", "evidence_id", ""),
        ("broker_balances", "read_only", False),
        ("broker_balances", "scope_verified", False),
        ("broker_balances", "observed_at_epoch", "1000"),
    ):
        rows = valid()
        rows[name][key] = value
        assert not check(rows)["certified"], (name, key)


def test_missing_provenance_or_pagination_denies():
    for field in REQUIRED:
        rows = valid()
        rows[field]["provenance"]["snapshot_complete"] = False
        assert not check(rows)["certified"]
    rows = valid()
    rows["open_order_reconciliation"]["provenance"][
        "complete_pagination_verified"
    ] = False
    assert not check(rows)["certified"]


def test_one_identity_cannot_impersonate_independent_source_types():
    registry = dict(TRUSTED)
    registry["account_identity"] = registry["writer_lease"]
    assert not evaluate_pretrade_certificate(
        valid(), account=ACCOUNT, trusted_provider_ids=registry, now_epoch=1000
    )["certified"]


def test_duplicate_provider_identity_or_evidence_is_rejected():
    duplicate_provider_ids = dict(TRUSTED)
    duplicate_provider_ids["account_identity"] = duplicate_provider_ids["account_permissions"]
    assert not evaluate_pretrade_certificate(
        valid(), account=ACCOUNT, trusted_provider_ids=duplicate_provider_ids,
        now_epoch=1000,
    )["certified"]

    observations = valid()
    observations["account_identity"]["evidence_id"] = observations[
        "account_permissions"
    ]["evidence_id"]
    result = check(observations)
    assert not result["certified"]
    assert {"account_permissions", "account_identity"}.issubset(result["missing"])


def test_max_age_cannot_be_extended():
    rows = valid(900)
    assert not check(rows, max_age_s=3600)["certified"]
