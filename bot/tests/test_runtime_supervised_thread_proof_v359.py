import types

from bot import runtime_supervised_thread_proof_v359_patch as v359


class _AliveCore:
    def is_alive(self):
        return True


class _HealthyRuntime:
    acquired = True
    lost = False
    _core_thread_registered = True
    _core_thread = _AliveCore()

    def _nija_lease_renewal_health(self):
        return True, "renewal_healthy", 1.0, 60.0

    def _core_thread_status(self):
        return True, True, "ok"


def test_v359_accepts_current_writer_with_healthy_renewal_and_registered_live_core():
    ok, detail = v359._writer_core_supervision_proof(_HealthyRuntime())
    assert ok is True
    assert "registered_core" in detail


def test_v359_rejects_missing_private_heartbeat_only_if_real_writer_core_proof_is_missing():
    runtime = _HealthyRuntime()
    assert not hasattr(runtime, "_heartbeat_thread")
    ok, _ = v359._writer_core_supervision_proof(runtime)
    assert ok is True


def test_v359_rejects_unhealthy_writer_renewal():
    runtime = _HealthyRuntime()
    runtime._nija_lease_renewal_health = types.MethodType(
        lambda self: (False, "stale", 61.0, 60.0), runtime
    )
    ok, detail = v359._writer_core_supervision_proof(runtime)
    assert ok is False
    assert detail == "renewal_unhealthy"


def test_v359_rejects_dead_or_unregistered_core():
    runtime = _HealthyRuntime()
    runtime._core_thread_status = types.MethodType(
        lambda self: (True, False, "core_thread_dead"), runtime
    )
    ok, detail = v359._writer_core_supervision_proof(runtime)
    assert ok is False
    assert detail.startswith("core_not_alive")

    runtime._core_thread_status = types.MethodType(
        lambda self: (False, False, "registration_pending"), runtime
    )
    ok, detail = v359._writer_core_supervision_proof(runtime)
    assert ok is False
    assert detail.startswith("core_not_registered")
