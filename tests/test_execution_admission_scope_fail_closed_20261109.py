"""Regression tests: admission diagnostics must not weaken account-scope validation."""
from __future__ import annotations

import sys
import types
from unittest.mock import patch

import pytest

from bot.execution_admission_acceptance_v468 import inspect_execution_admission


@pytest.mark.parametrize("account_scope", [
    "", " account", "account ", "account name", "account\tname", "account\nname", None,
])
def test_invalid_scope_is_never_reported_as_configured(account_scope):
    fake = types.ModuleType("preactivation_readiness_convergence_v16_patch")
    fake._strict_authority_ready = lambda: (True, "synthetic")
    fake._kill_switch_clear = lambda: (True, "synthetic")
    fake._genuine_execution_marker_proof = lambda: (True, "synthetic")
    with patch.dict(sys.modules, {"preactivation_readiness_convergence_v16_patch": fake}):
        result = inspect_execution_admission(account_scope)
    assert result["account_scope_configured"] is False
    assert result["pretrade_checks_passed"] is False
    assert result["eligible_for_existing_gate"] is False
    assert result["authorizes_orders"] is False
    assert result["dispatch_admission_granted"] is False


def test_valid_scope_without_collector_still_denied():
    fake = types.ModuleType("preactivation_readiness_convergence_v16_patch")
    fake._strict_authority_ready = lambda: (True, "synthetic")
    fake._kill_switch_clear = lambda: (True, "synthetic")
    fake._genuine_execution_marker_proof = lambda: (True, "synthetic")
    with patch.dict(sys.modules, {"preactivation_readiness_convergence_v16_patch": fake}):
        result = inspect_execution_admission("account-1")
    assert result["account_scope_configured"] is True
    assert result["pretrade_checks_passed"] is False
    assert result["eligible_for_existing_gate"] is False
    assert result["authorizes_orders"] is False
    assert result["dispatch_admission_granted"] is False
