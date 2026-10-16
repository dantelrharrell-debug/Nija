"""Cross-module checks for pretrade evidence and canonical runtime gates.

Proves that accepting current account evidence does not change the existing
canonical execution state or recovery decision.
"""
from bot.account_bound_pretrade_proof_v454 import CHECKS, assess
from bot.startup_recovery_readonly import classify_recovery


def test_fresh_pretrade_evidence_does_not_grant_canonical_orders():
    facts = {
        key: {
            "verified": True,
            "account": "platform:kraken",
            "source": "broker_readonly_account_probe",
            "observed_at": 1000.0,
        }
        for key in CHECKS
    }
    evidence = assess(facts, account="platform:kraken", now=1001.0)
    recovery = classify_recovery(
        {
            "broker_connected": True,
            "authority_ready": True,
            "capital_ready": True,
            "risk_ready": True,
            "strategy_ready": True,
            "nonce_ready": True,
            "position_sync_ready": True,
            "execution_ready": False,
        },
        kill_switch_clear=True,
        startup_attempts_reconciled=True,
        protective_exits_verified=True,
        ledger_reconciled=True,
    )
    assert evidence.pretrade_checks_pass is True
    assert evidence.can_submit_orders is False
    assert recovery.allow_new_orders is False
    assert "execution_ready" in recovery.reasons


def test_clear_execution_proof_does_not_bypass_protection():
    recovery = classify_recovery(
        dict.fromkeys(
            ("broker_connected", "authority_ready", "capital_ready",
             "risk_ready", "strategy_ready", "nonce_ready",
             "position_sync_ready", "execution_ready"), True
        ),
        kill_switch_clear=False,
        startup_attempts_reconciled=True,
        protective_exits_verified=False,
        ledger_reconciled=False,
    )
    assert recovery.allow_new_orders is False
    assert set(recovery.reasons) == {"kill_switch", "protective_exits", "ledger"}
