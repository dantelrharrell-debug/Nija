"""Regression coverage for collector replacement during a read-only observation."""
from bot import pretrade_independent_attestation as attestation


def test_collector_snapshot_survives_concurrent_replacement(monkeypatch):
    def replacement(_account):
        raise AssertionError("replacement collector must not run in this observation")

    def original(_account):
        attestation.install_authenticated_collector(replacement)
        return None

    monkeypatch.setattr(attestation, "_COLLECTOR", original)
    report = attestation.inspect_authenticated_attestations("platform:kraken")
    assert report["producer_status"] == "collector_result_invalid"
    assert report["collector_installed"] is True
    assert report["authorizes_orders"] is False
    assert all(value is False for value in report["checks"].values())


def test_missing_collector_denies(monkeypatch):
    monkeypatch.setattr(attestation, "_COLLECTOR", None)
    report = attestation.inspect_authenticated_attestations("platform:kraken")
    assert report["producer_status"] == "collector_missing"
    assert report["collector_installed"] is False
    assert report["authorizes_orders"] is False
