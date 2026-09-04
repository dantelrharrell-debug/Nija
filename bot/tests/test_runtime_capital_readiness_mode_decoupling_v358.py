from bot import runtime_capital_readiness_mode_decoupling_v358_patch as v358


def test_capital_proof_ready_accepts_fresh_positive_registered_capital():
    assert v358._capital_proof_ready({
        "hydrated": True,
        "stale": False,
        "real": 336.34,
        "registered": 3,
    }) is True


def test_capital_proof_ready_rejects_stale_or_unfunded_or_unregistered():
    assert v358._capital_proof_ready({"hydrated": True, "stale": True, "real": 336.34, "registered": 3}) is False
    assert v358._capital_proof_ready({"hydrated": True, "stale": False, "real": 0.0, "registered": 3}) is False
    assert v358._capital_proof_ready({"hydrated": True, "stale": False, "real": 336.34, "registered": 0}) is False
    assert v358._capital_proof_ready({"hydrated": False, "stale": False, "real": 336.34, "registered": 3}) is False


def test_capital_readiness_does_not_require_live_mode(monkeypatch):
    class FakeV16:
        @staticmethod
        def _collect_proofs():
            return ({
                "capital_ready": False,
                "execution_ready": False,
            }, {
                "capital": {
                    "hydrated": True,
                    "stale": False,
                    "real": 336.34,
                    "registered": 3,
                    "source": "capital_authority",
                },
                "live_mode": False,
            })

    fake = FakeV16()
    monkeypatch.setattr(v358, "_import_v16", lambda: fake)
    assert v358._patch_v16_collector() is True
    proofs, details = fake._collect_proofs()
    assert proofs["capital_ready"] is True
    assert proofs["execution_ready"] is False
    assert details["live_mode"] is False
    assert details["capital_ready_mode_decoupled"] is True
