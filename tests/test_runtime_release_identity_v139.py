from __future__ import annotations

import os
import sys
from types import ModuleType, SimpleNamespace

import secondary_venue_strict_readiness_patch as secondary
from bot import activation_publication_convergence_v136_patch as v136
from bot import activation_stop_capital_freshness_v135_patch as v135
from bot import readiness_proof_convergence_v134_patch as v134
from bot import runtime_release_identity_guard_patch as v139
from bot import runtime_release_manifest_patch as manifest


def test_v139_restores_declared_manifest_identity_after_legacy_downgrade(monkeypatch) -> None:
    declared = manifest.DECLARED_RELEASE_ID
    assert declared == "20260817-runtime-convergence-v138"

    monkeypatch.setattr(manifest, "RELEASE_ID", v136.RELEASE_ID)
    assert manifest.RELEASE_ID == "20260817-runtime-convergence-v136"

    assert v139.install_import_hook() is True
    assert manifest.RELEASE_ID == declared
    assert os.environ["NIJA_RUNTIME_RELEASE_IDENTITY_GUARD_INSTALLED"] == "1"


def test_v139_makes_v136_manifest_registration_flag_only(monkeypatch) -> None:
    declared = manifest.DECLARED_RELEASE_ID
    monkeypatch.setattr(manifest, "RELEASE_ID", declared)

    assert v139.install_import_hook() is True
    assert v136._patch_release_manifest() is True

    assert manifest.RELEASE_ID == declared
    assert manifest._REQUIRED_FLAGS["activation_publication_convergence_v136"] == (
        "NIJA_ACTIVATION_PUBLICATION_CONVERGENCE_V136_INSTALLED"
    )


def test_manifest_wires_v139_before_v136_and_requires_guard() -> None:
    guard = ("bot.runtime_release_identity_guard_patch", "install_import_hook")
    legacy = ("bot.activation_publication_convergence_v136_patch", "install_import_hook")

    assert guard in manifest._INSTALLERS
    assert legacy in manifest._INSTALLERS
    assert manifest._INSTALLERS.index(guard) < manifest._INSTALLERS.index(legacy)
    assert manifest._REQUIRED_FLAGS["runtime_release_identity_v139"] == (
        "NIJA_RUNTIME_RELEASE_IDENTITY_GUARD_INSTALLED"
    )


def test_v139_does_not_mutate_trading_safety_authority(monkeypatch) -> None:
    sentinels = {
        "NIJA_KILL_SWITCH": "true",
        "NIJA_NONCE_READY": "0",
        "NIJA_RUNTIME_NONCE_READY": "0",
        "NIJA_RUNTIME_EXECUTION_AUTHORITY": "0",
        "NIJA_PRE_DISPATCH_RISK_SIZING_READY": "1",
    }
    for key, value in sentinels.items():
        monkeypatch.setenv(key, value)

    assert v139.install_import_hook() is True

    for key, value in sentinels.items():
        assert os.environ[key] == value


def test_release_guard_runs_before_all_legacy_release_writers() -> None:
    guard = ("bot.runtime_release_identity_guard_patch", "install_import_hook")
    guard_index = manifest._INSTALLERS.index(guard)
    for entry in (
        ("bot.readiness_proof_convergence_v134_patch", "install_import_hook"),
        ("bot.activation_stop_capital_freshness_v135_patch", "install_import_hook"),
        ("bot.activation_publication_convergence_v136_patch", "install_import_hook"),
    ):
        assert guard_index < manifest._INSTALLERS.index(entry)


def test_v134_v135_v136_manifest_registration_is_flag_only(monkeypatch) -> None:
    declared = manifest.DECLARED_RELEASE_ID
    monkeypatch.setattr(manifest, "RELEASE_ID", declared)

    assert v139._patch_legacy_manifest_registrations() is True
    for module in (v134, v135, v136):
        assert module._patch_release_manifest() is True
        assert manifest.RELEASE_ID == declared

    assert manifest._REQUIRED_FLAGS["readiness_proof_convergence_v134"] == (
        "NIJA_READINESS_PROOF_CONVERGENCE_V134_INSTALLED"
    )
    assert manifest._REQUIRED_FLAGS["activation_stop_capital_freshness_v135"] == (
        "NIJA_ACTIVATION_STOP_CAPITAL_FRESHNESS_V135_INSTALLED"
    )
    assert manifest._REQUIRED_FLAGS["activation_publication_convergence_v136"] == (
        "NIJA_ACTIVATION_PUBLICATION_CONVERGENCE_V136_INSTALLED"
    )


def test_quiescent_audit_skips_installer_replay_when_healthy(monkeypatch) -> None:
    calls = {"repair": 0}

    def original_audit():
        calls["repair"] += 1
        return True, {"repair": "ran"}

    fake_manifest = SimpleNamespace(
        RELEASE_ID="release-v1",
        DECLARED_RELEASE_ID="release-v1",
        _INSTALLERS=(("legacy.installer", "install"),),
        _REQUIRED_FLAGS={},
        _audit=original_audit,
        _bounded_acyclic_scan=lambda details: False,
        _expected_scan_wrapper_release=lambda: "scan-v1",
        _scan_release_compatible=lambda actual, expected: actual == expected,
        _runtime_limits_consistent=lambda: (True, "limits-ok"),
        _readiness_contract_consistent=lambda: (True, "contract-ok"),
    )
    audit_module = SimpleNamespace(audit=lambda: (True, {"ok": True}))
    real_import = v139.importlib.import_module

    def fake_import(name: str):
        if name in {
            "runtime_module_identity_convergence_patch",
            "runtime_convergence_quiescence_patch",
            "scan_wrapper_depth_convergence_patch",
        }:
            return audit_module
        if name == "secondary_venue_strict_readiness_patch":
            return SimpleNamespace(refresh_readiness=lambda **kwargs: (True, [], {}))
        return real_import(name)

    monkeypatch.setattr(v139.importlib, "import_module", fake_import)
    monkeypatch.setenv("NIJA_SCAN_WRAPPER_RELEASE", "scan-v1")
    monkeypatch.delenv("NIJA_RUNTIME_RELEASE_ID", raising=False)

    assert v139._patch_manifest_audit(fake_manifest) is True
    ready, details = fake_manifest._audit()

    assert ready is True
    assert calls["repair"] == 0
    assert details["legacy.installer"] == "ok"


class _Broker:
    def __init__(self, name: str, connected: bool = True):
        self.broker_type = name
        self.connected = connected


def test_readiness_discovery_includes_canonical_private_manager(monkeypatch) -> None:
    manager_module = ModuleType("bot.multi_account_broker_manager")
    manager_module._manager = SimpleNamespace(
        _platform_brokers={
            "kraken": _Broker("kraken"),
            "coinbase": _Broker("coinbase"),
            "okx": _Broker("okx"),
        }
    )
    monkeypatch.setitem(sys.modules, "bot.multi_account_broker_manager", manager_module)
    monkeypatch.setitem(sys.modules, "multi_account_broker_manager", manager_module)
    monkeypatch.setattr(secondary, "_runtime_brokers", lambda: {})
    monkeypatch.setattr(secondary, "refresh_readiness", lambda **kwargs: (True, [], {}))

    assert v139._patch_secondary_runtime_broker_discovery() is True
    brokers = secondary._runtime_brokers()

    assert set(brokers) == {"kraken", "coinbase", "okx"}


def test_release_write_barrier_blocks_any_legacy_assignment() -> None:
    declared = manifest.DECLARED_RELEASE_ID
    assert v139._install_manifest_release_write_barrier() is True

    manifest.RELEASE_ID = v135.RELEASE_ID

    assert manifest.RELEASE_ID == declared
    assert os.environ["NIJA_RUNTIME_RELEASE_ID"] == declared


def test_declared_release_promotion_is_monotonic_and_blocks_v142_replay(monkeypatch) -> None:
    fake = v139._CanonicalReleaseManifestModule("fake_runtime_release_manifest")
    fake.DECLARED_RELEASE_ID = "20260818-runtime-convergence-v138"
    fake.RELEASE_ID = fake.DECLARED_RELEASE_ID

    fake.DECLARED_RELEASE_ID = "20260818-runtime-convergence-v146"
    assert fake.DECLARED_RELEASE_ID == "20260818-runtime-convergence-v146"
    assert fake.RELEASE_ID == "20260818-runtime-convergence-v146"

    fake.DECLARED_RELEASE_ID = "20260818-runtime-convergence-v142"
    fake.RELEASE_ID = "20260818-runtime-convergence-v142"

    assert fake.DECLARED_RELEASE_ID == "20260818-runtime-convergence-v146"
    assert fake.RELEASE_ID == "20260818-runtime-convergence-v146"


def test_release_rank_orders_date_then_version() -> None:
    assert v139._release_rank("20260818-runtime-convergence-v146") > v139._release_rank(
        "20260818-runtime-convergence-v142"
    )
    assert v139._release_rank("20260819-runtime-convergence-v1") > v139._release_rank(
        "20260818-runtime-convergence-v999"
    )
    assert v139._release_rank("not-a-release") is None
