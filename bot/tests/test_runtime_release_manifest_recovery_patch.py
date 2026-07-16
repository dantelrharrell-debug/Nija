from bot import runtime_release_manifest_patch as manifest


def test_bounded_acyclic_scan_is_accepted():
    details = {"scan_chain": "depth=10;max=24;broker_layers=1;canonical_layers=3;cycle=False"}
    assert manifest._bounded_acyclic_scan(details) is True


def test_cycle_is_not_accepted():
    details = {"scan_chain": "depth=10;max=24;broker_layers=1;canonical_layers=3;cycle=True"}
    assert manifest._bounded_acyclic_scan(details) is False


def test_excessive_depth_is_not_accepted():
    details = {"scan_chain": "depth=25;max=24;broker_layers=1;canonical_layers=3;cycle=False"}
    assert manifest._bounded_acyclic_scan(details) is False
