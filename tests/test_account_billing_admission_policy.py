"""Regression tests: suspension must never hide unverified brokerage exposure."""
from bot.account_billing_admission_policy import AccountEvidence, evaluate_account_policy


def test_unverified_billing_never_admits_trades():
    result = evaluate_account_policy(AccountEvidence(subscription_status="active"))
    assert not result.may_admit_new_trades
    assert result.must_reconcile_exposure


def test_suspended_member_with_unknown_exposure_still_reconciles():
    result = evaluate_account_policy(AccountEvidence(
        billing_verified=True, subscription_status="canceled"))
    assert not result.may_admit_new_trades
    assert result.must_reconcile_exposure


def test_suspended_member_with_verified_open_position_still_reconciles():
    result = evaluate_account_policy(AccountEvidence(
        billing_verified=True, subscription_status="past_due",
        exposure_verified=True, has_open_exposure=True))
    assert not result.may_admit_new_trades
    assert result.must_reconcile_exposure


def test_suspended_member_verified_flat_has_no_exposure_obligation():
    result = evaluate_account_policy(AccountEvidence(
        billing_verified=True, subscription_status="canceled",
        exposure_verified=True, has_open_exposure=False))
    assert not result.may_admit_new_trades
    assert not result.must_reconcile_exposure


def test_entitled_user_still_requires_independent_execution_gates():
    result = evaluate_account_policy(AccountEvidence(
        billing_verified=True, subscription_status="trialing",
        exposure_verified=True, has_open_exposure=False))
    assert result.may_admit_new_trades
    assert result.reason == "billing_entitled_execution_gates_required"


def test_unverified_exposure_cannot_be_declared_flat():
    result = evaluate_account_policy(AccountEvidence(
        billing_verified=True, subscription_status="canceled",
        exposure_verified=False, has_open_exposure=False))
    assert result.must_reconcile_exposure


def test_coverage_keeps_unknown_exposure_even_if_suspended():
    from bot.account_billing_admission_policy import coverage_scope_for_account
    assert coverage_scope_for_account(
        "user:member:kraken",
        AccountEvidence(billing_verified=True, subscription_status="canceled"),
    )


def test_coverage_excludes_only_verified_flat_suspended_account():
    from bot.account_billing_admission_policy import coverage_scope_for_account
    evidence = AccountEvidence(
        billing_verified=True, subscription_status="canceled",
        exposure_verified=True, has_open_exposure=False,
    )
    assert not coverage_scope_for_account("user:member:kraken", evidence, verified_flat=True)
    assert coverage_scope_for_account("platform:kraken", evidence, verified_flat=True)


def test_coverage_keeps_entitled_member_even_if_flat():
    from bot.account_billing_admission_policy import coverage_scope_for_account
    evidence = AccountEvidence(
        billing_verified=True, subscription_status="active",
        exposure_verified=True, has_open_exposure=False,
    )
    assert coverage_scope_for_account("user:member:kraken", evidence, verified_flat=True)
