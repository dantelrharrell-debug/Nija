"""Offline signed code/receipt handoff; no production approvals or broker I/O."""
import ast
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_kraken_startup_receipts import fixture  # noqa: F401 -- synthetic signing fixture
from test_kraken_canonical_startup_factory import wiring  # noqa: F401 -- synthetic owners
from bot import kraken_canonical_startup_factory as canonical
from bot import kraken_protected_startup_root as root
from bot import kraken_startup_evidence_binding as startup
from bot import pretrade_independent_attestation as attestation
from bot.kraken_startup_receipts import verify_startup_receipt_set

SOURCE = b'''
MARKER = "reviewed-synthetic-source"
def resolve_sources(*, manager, strategy, broker, trust, receipts):
    from nija_offline_protected_source_fixture import build
    return build(manager=manager, strategy=strategy, broker=broker, trust=trust, receipts=receipts)
def review_sources(sources, *, trust):
    from nija_offline_protected_source_fixture import review
    return review(sources, trust=trust)
'''


@pytest.fixture
def protected(wiring, tmp_path, monkeypatch, request):
    monkeypatch.setattr(root, "SECRET_ROOT", tmp_path)
    monkeypatch.setattr(startup, "_source_import_active", False)
    monkeypatch.delitem(sys.modules, root.MODULE_NAME, raising=False)
    request.addfinalizer(lambda: sys.modules.pop(root.MODULE_NAME, None))
    trust = wiring.signed.trust
    manifest = {
        "contract": root.CONTRACT,
        "trust": {
            name: getattr(trust, name) for name in root._TRUST_FIELDS
            if name not in {"public_keys", "reviewed_provider_ids"}
        },
        "receipts": dict(wiring.signed.binding.receipts),
    }
    manifest["trust"]["public_keys"] = {role: key.hex() for role, key in trust.public_keys.items()}
    manifest["trust"]["reviewed_provider_ids"] = dict(trust.reviewed_provider_ids)

    def write(source=SOURCE, change=None):
        payload = {**wiring.signed.payloads["independent_review"],
                   "artifact_sha256": hashlib.sha256(source).hexdigest()}
        manifest["receipts"]["independent_review"] = wiring.signed.sign("independent_review", payload)
        if change is not None:
            change(manifest)
        for name, content in ((root.MANIFEST_NAME, json.dumps(manifest).encode()),
                              (root.SOURCE_NAME, source)):
            path = tmp_path / name
            if path.exists():
                path.chmod(0o600)
            path.write_bytes(content)
            path.chmod(0o400)

    def build(**kwargs):
        assert kwargs["manager"] is wiring.sources.manager
        assert kwargs["strategy"] is wiring.sources.strategy
        assert kwargs["broker"] is wiring.sources.broker
        assert kwargs["trust"] == wiring.signed.trust
        return replace(wiring.sources, receipts=kwargs["receipts"])

    bridge = SimpleNamespace(build=Mock(side_effect=build), review=wiring.review)
    monkeypatch.setitem(sys.modules, "nija_offline_protected_source_fixture", bridge)
    write()
    return SimpleNamespace(wiring=wiring, manifest=manifest, write=write, bridge=bridge, directory=tmp_path)


def test_real_registration_is_passive_and_constructs_all_thirteen_later(protected):
    w = protected.wiring
    assert root.register_from_protected_root() == "protected_startup_factory_registered"
    assert startup.startup_binding_registration_state() == "registered"
    assert attestation._COLLECTOR is None
    protected.bridge.build.assert_not_called()
    w.review.assert_not_called()
    w.private_call.assert_not_called()
    binding = startup._factory(manager=w.sources.manager, strategy=w.sources.strategy)
    assert len(binding.providers) == 13
    assert startup._verify_receipts(binding) is True
    assert attestation._COLLECTOR is None
    w.private_call.assert_not_called()
    w.sources.independent_positions.assert_not_called()
    w.sources.independent_open_intents.assert_not_called()


def test_signed_handoff_uses_existing_atomic_installer_without_order_authority(protected, monkeypatch):
    w = protected.wiring
    monkeypatch.setattr(canonical, "compose_authenticated_kraken_collector_sources",
                        lambda **kwargs: w.signed.binding.providers)
    assert root.register_from_protected_root() == "protected_startup_factory_registered"
    assert startup.install_from_canonical_startup(w.sources.manager, w.sources.strategy) == (
        "diagnostic_collector_installed"
    )
    report = attestation.inspect_authenticated_attestations("platform:kraken")
    assert all(report["checks"].values())
    assert report["authorizes_orders"] is False
    w.private_call.assert_not_called()


@pytest.mark.parametrize("role", sorted(startup.RECEIPTS))
def test_each_bad_signature_denies_before_source_execution(protected, monkeypatch, role):
    def change(manifest):
        envelope = json.loads(manifest["receipts"][role])
        envelope["payload"]["status"] = "not-certified"
        manifest["receipts"][role] = json.dumps(envelope)
    protected.write(change=change)
    load = Mock()
    monkeypatch.setattr(root, "_load_verified_source", load)
    assert root.register_from_protected_root() == "protected_startup_receipts_denied"
    load.assert_not_called()
    assert startup.startup_binding_registration_state() == "missing"


@pytest.mark.parametrize("role", sorted(startup.RECEIPTS))
def test_each_missing_certification_denies_before_source_execution(protected, monkeypatch, role):
    protected.write(change=lambda manifest: manifest["receipts"].pop(role))
    load = Mock()
    monkeypatch.setattr(root, "_load_verified_source", load)
    assert root.register_from_protected_root() == "protected_startup_receipts_denied"
    load.assert_not_called()


def test_changed_source_bytes_deny_before_loading(protected, monkeypatch):
    path = protected.directory / root.SOURCE_NAME
    path.chmod(0o600)
    path.write_bytes(SOURCE + b'\nMARKER = "changed"\n')
    load = Mock()
    monkeypatch.setattr(root, "_load_verified_source", load)
    assert root.register_from_protected_root() == "protected_startup_source_digest_denied"
    load.assert_not_called()


def test_no_second_source_read_or_bytecode_cache_can_swap_reviewed_bytes(protected, monkeypatch):
    original = root._load_verified_source
    loaded = []
    def load(source):
        path = protected.directory / root.SOURCE_NAME
        path.chmod(0o600)
        path.write_bytes(b'raise RuntimeError("unreviewed-file-swap")')
        module = original(source)
        loaded.append(module.MARKER)
        return module
    monkeypatch.setattr(root, "_load_verified_source", load)
    assert root.register_from_protected_root() == "protected_startup_factory_registered"
    assert loaded == ["reviewed-synthetic-source"]
    assert not (protected.directory / "__pycache__").exists()


@pytest.mark.parametrize("field", ["RENDER_SERVICE_ID", "RENDER_GIT_COMMIT"])
def test_runtime_scope_change_before_loading_denies(protected, monkeypatch, field):
    monkeypatch.setenv(field, "different-runtime")
    load = Mock()
    monkeypatch.setattr(root, "_load_verified_source", load)
    assert root.register_from_protected_root() == "protected_startup_receipts_denied"
    load.assert_not_called()


def test_runtime_change_during_loading_denies_registration(protected, monkeypatch):
    original = root._load_verified_source
    def load(source):
        module = original(source)
        monkeypatch.setenv("RENDER_GIT_COMMIT", "changed-after-validation")
        return module
    monkeypatch.setattr(root, "_load_verified_source", load)
    assert root.register_from_protected_root() == "protected_startup_receipts_denied"
    assert startup.startup_binding_registration_state() == "missing"


def test_expiry_during_source_loading_denies(protected, monkeypatch):
    now = protected.wiring.signed.now
    ticks = iter([now, now, now + 31])
    monkeypatch.setattr(root, "verify_startup_receipt_set", lambda receipts, trust: (
        verify_startup_receipt_set(receipts, trust, clock=lambda: next(ticks))
    ))
    assert root.register_from_protected_root() == "protected_startup_receipts_denied"
    assert startup.startup_binding_registration_state() == "missing"


@pytest.mark.parametrize("source", [b'raise RuntimeError("private-source-payload")', b"invalid python :",
                                   b'raise SystemExit("private-source-payload")',
                                   b"def resolve_sources(**kwargs): return None"])
def test_bad_approved_source_denies_without_exporting_contents(protected, capsys, source):
    protected.write(source=source)
    result = root.register_from_protected_root()
    assert result in {"protected_startup_registration_denied", "protected_startup_source_interface_denied"}
    assert startup.startup_binding_registration_state() == "missing"
    assert "private-source-payload" not in repr(capsys.readouterr())


def test_approved_source_cannot_accidentally_self_register_during_import(protected):
    protected.write(source=b'''from bot.kraken_startup_evidence_binding import register_reviewed_startup_binding
register_reviewed_startup_binding(lambda **kwargs: None, verify_receipts=lambda binding: False)
''')
    assert root.register_from_protected_root() == "protected_startup_registration_denied"
    assert startup.startup_binding_registration_state() == "missing"
    assert startup._source_import_active is False


def test_resolver_cannot_substitute_signed_receipts(protected):
    assert root.register_from_protected_root() == "protected_startup_factory_registered"
    protected.bridge.build.side_effect = None
    protected.bridge.build.return_value = protected.wiring.sources
    w = protected.wiring
    with pytest.raises(canonical.CanonicalKrakenStartupDenied, match="canonical_startup_source_binding_denied"):
        startup._factory(manager=w.sources.manager, strategy=w.sources.strategy)
    assert attestation._COLLECTOR is None
    w.private_call.assert_not_called()


@pytest.mark.parametrize("name", [root.SOURCE_NAME, root.MANIFEST_NAME])
def test_missing_artifacts_leave_existing_monitoring_and_collector_untouched(protected, monkeypatch, name):
    previous = object()
    monkeypatch.setattr(attestation, "_COLLECTOR", previous)
    (protected.directory / name).unlink()
    assert root.register_from_protected_root() == "protected_startup_artifacts_missing"
    assert attestation._COLLECTOR is previous


@pytest.mark.parametrize("change", [
    lambda m: m.update(contract="unrecognized"),
    lambda m: m.update(unexpected=True),
    lambda m: m["trust"].update(unexpected=True),
    lambda m: m["trust"].update(public_keys={"independent_review": "not-a-public-value"}),
])
def test_invalid_protected_manifest_denies(protected, change):
    protected.write(change=change)
    assert root.register_from_protected_root() == "protected_startup_registration_denied"
    assert startup.startup_binding_registration_state() == "missing"


def test_duplicate_manifest_keys_deny(protected):
    path = protected.directory / root.MANIFEST_NAME
    path.chmod(0o600)
    path.write_text('{"contract":"one","contract":"two"}')
    assert root.register_from_protected_root() == "protected_startup_registration_denied"


@pytest.mark.parametrize("name", [root.SOURCE_NAME, root.MANIFEST_NAME])
def test_group_or_world_writable_files_deny(protected, name):
    (protected.directory / name).chmod(0o622)
    assert root.register_from_protected_root() == "protected_startup_registration_denied"


def test_render_style_internal_secret_symlinks_are_supported(protected):
    version = protected.directory / "..version"
    version.mkdir()
    for name in (root.MANIFEST_NAME, root.SOURCE_NAME):
        path = protected.directory / name
        path.rename(version / name)
        path.symlink_to(version / name)
    assert root.register_from_protected_root() == "protected_startup_factory_registered"


def test_standard_module_identity_supports_passive_reviewed_classes(protected):
    protected.write(source=b'''from dataclasses import dataclass
@dataclass
class Passive:
    value: str
''' + SOURCE)
    assert root.register_from_protected_root() == "protected_startup_factory_registered"
    assert sys.modules[root.MODULE_NAME].Passive("synthetic").value == "synthetic"


@pytest.mark.parametrize("name", [root.SOURCE_NAME, root.MANIFEST_NAME])
def test_oversized_protected_artifacts_deny_before_execution(protected, monkeypatch, name):
    path = protected.directory / name
    path.chmod(0o600)
    path.write_bytes(b"x" * 131073)
    load = Mock()
    monkeypatch.setattr(root, "_load_verified_source", load)
    assert root.register_from_protected_root() == "protected_startup_registration_denied"
    load.assert_not_called()


def test_secret_symlink_outside_protected_mount_denies(protected):
    outside = protected.directory.parent / "unapproved-source.py"
    outside.write_bytes(SOURCE)
    path = protected.directory / root.SOURCE_NAME
    path.unlink()
    path.symlink_to(outside)
    assert root.register_from_protected_root() == "protected_startup_registration_denied"


def test_nonregular_source_does_not_block_on_read(protected):
    path = protected.directory / root.SOURCE_NAME
    path.unlink()
    os.mkfifo(path, mode=0o600)
    assert root.register_from_protected_root() == "protected_startup_registration_denied"


def test_preexisting_registration_is_preserved_without_loading_files(protected, monkeypatch):
    existing_factory, existing_verify = Mock(), Mock()
    startup.register_reviewed_startup_binding(existing_factory, verify_receipts=existing_verify)
    read = Mock()
    monkeypatch.setattr(root, "_read_protected", read)
    assert root.register_from_protected_root() == "existing_startup_binding_preserved"
    assert startup._factory is existing_factory and startup._verify_receipts is existing_verify
    read.assert_not_called()


def test_partial_registration_is_not_overwritten(protected, monkeypatch):
    existing = object()
    monkeypatch.setattr(startup, "_factory", existing)
    assert root.register_from_protected_root() == "incomplete_startup_binding_preserved"
    assert startup._factory is existing


def test_preexisting_module_identity_is_not_replaced(protected, monkeypatch):
    existing = object()
    monkeypatch.setitem(sys.modules, root.MODULE_NAME, existing)
    assert root.register_from_protected_root() == "protected_startup_registration_denied"
    assert sys.modules[root.MODULE_NAME] is existing
    assert startup.startup_binding_registration_state() == "missing"


def test_environment_paths_or_approval_flags_cannot_select_code(protected, monkeypatch):
    (protected.directory / root.MANIFEST_NAME).unlink()
    monkeypatch.setenv("NIJA_COLLECTOR_CERTIFIED", "true")
    monkeypatch.setenv("NIJA_KRAKEN_STARTUP_ROOT", str(protected.directory / root.SOURCE_NAME))
    assert root.register_from_protected_root() == "protected_startup_artifacts_missing"


def test_final_interpreter_registers_after_outer_exec_loses_old_registry(protected):
    # The only signers and protected sources here are ephemeral synthetic fixtures.
    prefix = (
        f"import sys, types; sys.path[:] = {sys.path!r}; "
        "package = types.ModuleType('bot'); package.__path__ = ['bot']; sys.modules['bot'] = package; "
    )
    child = prefix + (
        "from pathlib import Path; from bot import kraken_protected_startup_root as root; "
        f"root.SECRET_ROOT = Path({str(protected.directory)!r}); "
        "print(root.register_from_protected_root())"
    )
    bootstrap = prefix + (
        "import os; from bot.kraken_startup_evidence_binding import register_reviewed_startup_binding; "
        "register_reviewed_startup_binding(lambda **kwargs: None, verify_receipts=lambda binding: False); "
        f"os.execv(sys.executable, [sys.executable, '-S', '-c', {child!r}])"
    )
    result = subprocess.run([sys.executable, "-S", "-c", bootstrap],
                            cwd=Path(__file__).parents[1], capture_output=True, text=True, timeout=15, check=True)
    assert result.stdout.strip() == "protected_startup_factory_registered"
    assert result.stderr == ""
    assert startup.startup_binding_registration_state() == "missing"


def test_real_bot_main_calls_protected_registration_after_strategy_before_install_and_engine():
    tree = ast.parse((Path(__file__).parents[1] / "bot/bot_main.py").read_text())
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = {n.func.id: n.lineno for n in ast.walk(main)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert calls["_publish_canonical_strategy_for_runtime"] < calls["register_from_protected_root"]
    assert calls["register_from_protected_root"] < calls["install_from_canonical_startup"]
    assert calls["install_from_canonical_startup"] < calls["start_trading_engine"]
