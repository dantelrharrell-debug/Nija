from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "bot" / "writer_authority_generation_convergence_v57_patch.py"
BOT_ENTRYPOINT = ROOT / "bot" / "bot.py"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PATCH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _install_v45(monkeypatch, *, proof, reason="") -> ModuleType:
    v45 = ModuleType("bot.writer_generation_handoff_v45_patch")
    v45._prove_process_writer = lambda: (proof, reason)

    def repair(source: str):
        if proof is None:
            return False, 0, reason or "proof_failed"
        generation = int(proof["generation"])
        value = str(generation)
        os.environ["NIJA_WRITER_LEASE_GENERATION"] = value
        os.environ["NIJA_WRITER_GENERATION"] = value
        os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] = value
        return True, generation, "proof_verified"

    v45.repair_process_generation = repair
    monkeypatch.setitem(sys.modules, "bot.writer_generation_handoff_v45_patch", v45)
    return v45


def _eac() -> ModuleType:
    module = ModuleType("bot.execution_authority_context")
    module.assert_distributed_writer_authority = lambda: None
    module._FENCE_LAST_CHECK_TS = 0.0
    module._FENCE_LAST_OK = False
    module._FENCE_LAST_ERR = "stale"
    return module


def test_stale_local_generation_repairs_only_after_exact_proof(monkeypatch) -> None:
    v57 = _load("test_writer_authority_v57_repair")
    proof = {
        "generation": 3359,
        "token": "2056-token",
        "pttl_ms": 118993,
    }
    _install_v45(monkeypatch, proof=proof)
    eac = _eac()

    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "3358")
    monkeypatch.setenv("NIJA_WRITER_GENERATION", "3358")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION_LAST", "3358")

    assert v57._patch_execution_authority_context(eac) is True
    eac.assert_distributed_writer_authority()

    assert os.environ["NIJA_WRITER_LEASE_GENERATION"] == "3359"
    assert os.environ["NIJA_WRITER_GENERATION"] == "3359"
    assert os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] == "3359"
    assert os.environ["NIJA_WRITER_LEASE_ACQUIRED"] == "1"
    assert eac._FENCE_LAST_OK is True
    assert eac._FENCE_LAST_ERR == ""


def test_missing_exact_proof_stays_fail_closed(monkeypatch) -> None:
    v57 = _load("test_writer_authority_v57_fail_closed")
    _install_v45(monkeypatch, proof=None, reason="redis_lock_missing")
    eac = _eac()
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "3358")

    assert v57._patch_execution_authority_context(eac) is True
    with pytest.raises(RuntimeError, match="exact process writer proof failed:redis_lock_missing"):
        eac.assert_distributed_writer_authority()

    assert os.environ["NIJA_WRITER_LEASE_GENERATION"] == "3358"
    assert eac._FENCE_LAST_OK is False


def test_live_bypass_is_still_rejected(monkeypatch) -> None:
    v57 = _load("test_writer_authority_v57_bypass")
    proof = {"generation": 3359, "token": "2056-token", "pttl_ms": 1000}
    _install_v45(monkeypatch, proof=proof)
    eac = _eac()

    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK", "true")

    assert v57._patch_execution_authority_context(eac) is True
    with pytest.raises(RuntimeError, match="live distributed-lock bypass refused"):
        eac.assert_distributed_writer_authority()


def test_canonical_fast_path_installs_v57() -> None:
    source = BOT_ENTRYPOINT.read_text(encoding="utf-8")
    fast_block = source.split("_FAST_PATH_INSTALLERS = (", 1)[1].split(
        ")\n\n_LEGACY_INSTALLERS", 1
    )[0]

    assert "writer_authority_generation_convergence_v57_patch" in fast_block
    assert "WRITER_AUTHORITY_GENERATION_CONVERGENCE_V57" in fast_block
