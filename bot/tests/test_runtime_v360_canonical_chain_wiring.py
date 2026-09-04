from pathlib import Path


def test_v360_supervised_thread_proof_is_canonical_chain_stage():
    chain = Path("bot/runtime_all_in_profitability_authority_v324_patch.py").read_text()
    assert '"v360", "bot.runtime_supervised_thread_proof_v360_patch"' in chain
    assert '"NIJA_RUNTIME_SUPERVISED_THREAD_PROOF_V360_READY"' in chain
    assert "v359=true v360=true" in chain
    assert "supervised_thread_proof_uses_current_writer_renewal_and_registered_core=true" in chain


def test_v360_does_not_replace_confirmed_fill_execution_truth():
    repair = Path("bot/runtime_supervised_thread_proof_v360_patch.py").read_text()
    assert "execution_proof_fabricated=false" in repair
    assert "execution_authority_granted=false" in repair
    assert "forced_activation=false" in repair
    assert "registered_core_alive=true" in repair
    assert "renewal_healthy=true" in repair
