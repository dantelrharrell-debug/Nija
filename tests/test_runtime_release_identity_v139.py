from __future__ import annotations

import os

from bot import activation_publication_convergence_v136_patch as v136
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
