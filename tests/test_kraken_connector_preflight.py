"""Preflight uses synthetic signatures only, and never calls a broker."""
import json
import sys

import pytest

from bot import kraken_connector_preflight as preflight
from bot import kraken_protected_startup_root as root
from bot import kraken_startup_evidence_binding as startup
from test_kraken_canonical_startup_factory import wiring  # noqa: F401
from test_kraken_protected_startup_root import protected  # noqa: F401
from test_kraken_startup_receipts import fixture  # noqa: F401


def test_valid_signed_source_is_not_imported_or_registered(protected, capsys):
    protected.write(source=b'raise AssertionError("must never execute")')
    assert preflight.main() == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": preflight.PASS,
        "source_executed": False,
        "collector_checked": False,
        "authorizes_orders": False,
    }
    assert root.MODULE_NAME not in sys.modules
    assert startup.startup_binding_registration_state() == "missing"
    protected.wiring.private_call.assert_not_called()


@pytest.mark.parametrize(("name", "status"), [
    (root.MANIFEST_NAME, "protected_manifest_missing"),
    (root.SOURCE_NAME, "protected_source_missing"),
])
def test_missing_file_is_identified(protected, name, status):
    (protected.directory / name).unlink()
    assert preflight.inspect_protected_artifacts() == status


@pytest.mark.parametrize(("name", "status"), [
    (root.MANIFEST_NAME, "protected_manifest_unreadable_or_unsafe"),
    (root.SOURCE_NAME, "protected_source_unreadable_or_unsafe"),
])
def test_group_write_permission_rejected(protected, name, status):
    (protected.directory / name).chmod(0o620)
    assert preflight.inspect_protected_artifacts() == status


def test_manifest_does_not_disclose_private_fields(protected, capsys):
    protected.write(change=lambda manifest: manifest.update(private="private-marker"))
    assert preflight.main() == 1
    stdout = capsys.readouterr().out
    assert json.loads(stdout)["status"] == "protected_manifest_invalid"
    assert "private-marker" not in stdout


def test_missing_receipt_rejected(protected):
    protected.write(change=lambda manifest: manifest["receipts"].pop("backup_restore"))
    assert preflight.inspect_protected_artifacts() == "protected_receipts_or_runtime_scope_denied"


def test_invalid_signature_rejected(protected):
    def tamper(manifest):
        envelope = json.loads(manifest["receipts"]["backup_restore"])
        envelope["payload"]["artifact_sha256"] = "0" * 64
        manifest["receipts"]["backup_restore"] = json.dumps(envelope)

    protected.write(change=tamper)
    assert preflight.inspect_protected_artifacts() == "protected_receipts_or_runtime_scope_denied"


def test_runtime_release_mismatch_rejected(protected, monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "0" * 40)
    assert preflight.inspect_protected_artifacts() == "protected_receipts_or_runtime_scope_denied"


def test_changed_source_rejected(protected):
    path = protected.directory / root.SOURCE_NAME
    path.chmod(0o600)
    path.write_bytes(b"changed after review")
    assert preflight.inspect_protected_artifacts() == "protected_source_digest_mismatch"


def test_receipts_rechecked_after_source_read(protected, monkeypatch):
    read_protected = preflight._read_protected

    def read_with_runtime_change(name, maximum):
        if name == root.SOURCE_NAME:
            monkeypatch.setenv("RENDER_GIT_COMMIT", "0" * 40)
        return read_protected(name, maximum)

    monkeypatch.setattr(preflight, "_read_protected", read_with_runtime_change)
    assert preflight.inspect_protected_artifacts() == "protected_receipts_or_runtime_scope_denied"
