"""Regression tests for IONOS source-byte pinning; no Stripe network or payment."""
import hashlib
import json
import os

import pytest

from game_sandbox.app import from_environment
from game_sandbox.service import Denied, Manifest, digest


def configure(tmp_path, monkeypatch):
    source = tmp_path / "canonical_ionos_export.zip"
    source.write_bytes(b"fictional isolated IONOS export used for fixture tests")
    manifest_raw = {
        "version": "synthetic-test-shape-v1",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "structure": "12_total",
        "challenges": [{
            "rounds": [{"id": "round_" + str(i), "choices": 3} for i in range(12)],
        }],
    }
    manifest = Manifest(manifest_raw)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_raw))
    adapter_path = tmp_path / "report_adapter.py"
    adapter_path.write_text("def build_report(answers):\n    return {'synthetic_test_only': True, 'n': len(answers)}\n")
    env = {
        "NIJA_IQ_SANDBOX_ENABLED": "true",
        "NIJA_IQ_SANDBOX_INGRESS_MODE": "direct",
        "NIJA_IQ_SANDBOX_DATABASE": str(tmp_path / "trading_iq_sandbox.sqlite3"),
        "NIJA_IQ_SANDBOX_ORIGIN": "https://sandbox.nija.invalid",
        "NIJA_IQ_SANDBOX_STRIPE_KEY": "rk_test_fixture_not_a_real_key",
        "NIJA_IQ_SANDBOX_WEBHOOK_SECRET": "whsec_fixture_not_a_real_secret",  # pragma: allowlist secret -- synthetic test only
        "NIJA_IQ_SANDBOX_PRICE_ID": "price_fixture",
        "NIJA_IQ_SANDBOX_PRODUCT_ID": "prod_fixture",
        "NIJA_IQ_SANDBOX_SOURCE_EXPORT": str(source),
        "NIJA_IQ_SANDBOX_MANIFEST": str(manifest_path),
        "NIJA_IQ_SANDBOX_MANIFEST_SHA256": manifest.digest,
        "NIJA_IQ_SANDBOX_REPORT_ADAPTER": str(adapter_path),
        "NIJA_IQ_SANDBOX_REPORT_ADAPTER_SHA256": digest(adapter_path.read_text()),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return source, manifest, env


def test_export_source_hash_must_match_reviewed_manifest(tmp_path, monkeypatch):
    source, manifest, env = configure(tmp_path, monkeypatch)
    app = from_environment()
    result = app.test_client().get("/sandbox/health")
    assert result.status_code == 200
    assert result.json == {"sandbox": True, "live_payments": False, "manifest": manifest.digest}
    assert (tmp_path / "trading_iq_sandbox.sqlite3").exists()

    # A byte-for-byte changed game source cannot start the report/payment backend.
    source.write_bytes(source.read_bytes() + b"\nchange after review")
    with pytest.raises(Denied, match="reviewed_ionos_source_export_required"):
        from_environment()


def test_missing_source_export_denies_startup(tmp_path, monkeypatch):
    source, _manifest, _env = configure(tmp_path, monkeypatch)
    source.unlink()
    with pytest.raises(Denied, match="reviewed_ionos_source_export_required"):
        from_environment()


def test_source_symlink_denies_startup_even_if_digest_matches(tmp_path, monkeypatch):
    source, _manifest, _env = configure(tmp_path, monkeypatch)
    actual = tmp_path / "actual_source.zip"
    source.rename(actual)
    try:
        source.symlink_to(actual)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this test filesystem")
    with pytest.raises(Denied, match="reviewed_ionos_source_export_required"):
        from_environment()


def test_wrong_manifest_pin_denies_startup(tmp_path, monkeypatch):
    _source, _manifest, _env = configure(tmp_path, monkeypatch)
    monkeypatch.setenv("NIJA_IQ_SANDBOX_MANIFEST_SHA256", "0" * 64)
    with pytest.raises(Denied, match="reviewed_manifest_pin_required"):
        from_environment()
