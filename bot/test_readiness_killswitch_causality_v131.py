from bot.readiness_killswitch_causality_v131_patch import _causal_activation


def test_restart_file_record_recovers_prior_cause():
    status = {"recent_history": [
        {"reason": "AUTHORITY_HEARTBEAT_EXPIRED: core_thread_dead — NIJA_CORE_THREAD_ALIVE is not set", "source": "AUTO"},
        {"reason": "Kill switch file detected", "source": "FILE_SYSTEM"},
    ]}
    reason, source = _causal_activation(status)
    assert source == "AUTO"
    assert "AUTHORITY_HEARTBEAT_EXPIRED" in reason
    assert "core_thread_dead" in reason


def test_manual_stop_is_never_reclassified():
    status = {"recent_history": [
        {"reason": "operator stop", "source": "MANUAL"},
    ]}
    assert _causal_activation(status) == ("operator stop", "MANUAL")


def test_explicit_filesystem_stop_is_not_reclassified():
    status = {"recent_history": [
        {"reason": "operator created emergency marker", "source": "FILE_SYSTEM"},
    ]}
    assert _causal_activation(status) == ("operator created emergency marker", "FILE_SYSTEM")


def test_v131_source_preserves_safety_contract():
    import inspect
    import bot.readiness_killswitch_causality_v131_patch as patch

    src = inspect.getsource(patch)
    assert '"authority_ready", "execution_ready"' not in src
    assert "generic_auto_clear=false" in src
    assert "risk_gates_unchanged=true" in src
    assert "readiness_synthetic=false" in src
    assert "execution_authority_unchanged=true" in src
    assert "_patch_v16_truth_sync" in src
