from __future__ import annotations

from pathlib import Path

from scripts import apply_user_refresh_stale_inflight_v409 as patcher


def test_v412_preserves_v421_critical_monitor_start_order(tmp_path: Path, monkeypatch) -> None:
    v88 = tmp_path / "production_runtime_convergence_v88_patch.py"
    v88.write_text(
        '''def _monitor() -> None:\n'''
        '''    deadline = time.monotonic() + 600.0\n'''
        '''    while time.monotonic() < deadline:\n'''
        '''        _install_kraken_user_supervision()\n'''
        '''        if _try_patch_loaded():\n'''
        '''            return\n'''
        '''        time.sleep(0.25)\n'''
        '''    LOGGER.warning("PRODUCTION_RUNTIME_CONVERGENCE_V88_MONITOR_EXPIRED marker=%s", MARKER)\n'''
        '''\n'''
        '''def install_import_hook() -> bool:\n'''
        '''    global _MONITOR_STARTED, _CRITICAL_LIVENESS_MONITOR_STARTED\n'''
        '''    _install_stale_startup_log_filter()\n'''
        '''    with _LOCK:\n'''
        '''        if not _CRITICAL_LIVENESS_MONITOR_STARTED:\n'''
        '''            _CRITICAL_LIVENESS_MONITOR_STARTED = True\n'''
        '''            threading.Thread(\n'''
        '''                target=_critical_liveness_monitor,\n'''
        '''                name="CriticalKrakenLivenessV420",\n'''
        '''                daemon=True,\n'''
        '''            ).start()\n'''
        '''    _install_kraken_user_supervision()\n'''
        '''    _try_patch_loaded()\n'''
        '''    LOGGER.critical(\n'''
        '''        "PRODUCTION_RUNTIME_CONVERGENCE_V88_INSTALLED marker=%s circuit_classification=true "\n'''
        '''        "kraken_user_supervision=true kraken_user_rebuild_v90=true all_account_connectivity_v266=true "\n'''
        '''        MARKER,\n'''
        '''    )\n'''
        '''    return True\n''',
        encoding="utf-8",
    )
    monkeypatch.setattr(patcher, "V88", v88)

    assert patcher._patch_v412() is True

    text = v88.read_text(encoding="utf-8")
    critical = text.index("target=_critical_liveness_monitor")
    supervision = text.index("kraken_ready = bool(_install_kraken_user_supervision())")
    assert critical < supervision
    assert "tsm_ready = bool(_try_patch_loaded())" in text
    assert "PRODUCTION_RUNTIME_CONVERGENCE_V412_WAIT" in text
    assert patcher.V412_MARKER in text
