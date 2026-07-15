from __future__ import annotations

from source_runtime_guard_bootstrap import _scan_chain_structurally_safe


def test_accepts_bounded_acyclic_chain_with_copied_markers():
    details = {
        "scan_chain": (
            "depth=13;max=24;broker_layers=0;canonical_layers=6;cycle=False;"
            "head=_patch_core_loop.<locals>.run_scan_phase;tail=NijaCoreLoop.run_scan_phase"
        )
    }
    assert _scan_chain_structurally_safe(details) is True


def test_rejects_cycle_even_below_depth_limit():
    assert _scan_chain_structurally_safe(
        {"scan_chain": "depth=13;max=24;broker_layers=0;canonical_layers=6;cycle=True;head=x;tail=y"}
    ) is False


def test_rejects_excessive_depth():
    assert _scan_chain_structurally_safe(
        {"scan_chain": "depth=25;max=24;broker_layers=0;canonical_layers=1;cycle=False;head=x;tail=y"}
    ) is False
