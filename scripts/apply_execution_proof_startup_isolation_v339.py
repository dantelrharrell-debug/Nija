"""Apply NIJA execution-proof startup isolation v339.

Production on 2026-08-31 exposed a startup-order race: the canonical writer could
refresh the legacy HEARTBEAT_MARKER_PATH before v169 installed. That authority
liveness write used FILL_VERIFY and could be accepted by the pre-v169 verifier.
Once v169 installed it correctly rejected the stale authority marker, leaving
activation fail-closed on proof.execution_ready.

v339 closes that race without fabricating execution proof or weakening any
writer, nonce, risk, capital, position, kill-switch, ECEL, order, ACK or fill
safety gate.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PATH = ROOT / "scripts" / "canonical_runtime_launcher_v26.py"
V169_PATH = ROOT / "bot" / "runtime_execution_capital_integrity_v169_patch.py"
V238_PATH = ROOT / "bot" / "runtime_heartbeat_marker_convergence_v238_patch.py"
MARKER = "20260831-execution-proof-startup-isolation-v339"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"v339 anchor missing: {label}")
    return text.replace(old, new, 1)


def patch_launcher_text(text: str) -> str:
    prepare = '''def _prepare_execution_proof_startup_isolation_v339() -> None:\n    """Route pre-v169 writer liveness away from the execution-proof marker."""\n    execution_path = str(\n        os.environ.get("NIJA_EXECUTION_MARKER_PATH", "")\n        or os.environ.get("HEARTBEAT_MARKER_PATH", "")\n        or "./data/heartbeat_verified.flag"\n    ).strip()\n    authority_path = str(\n        os.environ.get("NIJA_AUTHORITY_LIVENESS_MARKER_PATH", "")\n        or "./data/authority_heartbeat.flag"\n    ).strip()\n    if not execution_path or not authority_path:\n        raise RuntimeError("execution-proof v339 marker path missing")\n    if Path(execution_path).resolve() == Path(authority_path).resolve():\n        raise RuntimeError("execution-proof v339 authority/execution marker paths collide")\n    os.environ["NIJA_EXECUTION_MARKER_PATH"] = execution_path\n    os.environ["NIJA_AUTHORITY_LIVENESS_MARKER_PATH"] = authority_path\n    # Until v169 patches all authority writers, legacy heartbeat code is\n    # physically routed away from the execution-proof path.\n    os.environ["HEARTBEAT_MARKER_PATH"] = authority_path\n    os.environ["NIJA_EXECUTION_PROOF_STARTUP_ISOLATION_V339_ARMED"] = "1"\n    LOGGER.critical(\n        "EXECUTION_PROOF_STARTUP_ISOLATION_V339_ARMED "\n        "marker=20260831-execution-proof-startup-isolation-v339 "\n        "authority_path=%s execution_path=%s pre_v169_authority_routed=true "\n        "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",\n        authority_path,\n        execution_path,\n    )\n\n\n'''
    if "def _prepare_execution_proof_startup_isolation_v339()" not in text:
        anchor = "def _bootstrap_writer_first() -> tuple[ModuleType, ModuleType]:\n"
        if anchor not in text:
            raise RuntimeError("v339 launcher bootstrap anchor missing")
        text = text.replace(anchor, prepare + anchor, 1)

    text = _replace_once(
        text,
        '''    _start_render_memory_pressure_guard()\n    install_canonical_startup_guard()\n    bot_entry, bot_main = _bootstrap_writer_first()\n''',
        '''    _start_render_memory_pressure_guard()\n    _prepare_execution_proof_startup_isolation_v339()\n    install_canonical_startup_guard()\n    bot_entry, bot_main = _bootstrap_writer_first()\n''',
        "launcher main ordering",
    )
    if text.index("_prepare_execution_proof_startup_isolation_v339()", text.index("def main()")) > text.index("install_canonical_startup_guard()", text.index("def main()")):
        raise RuntimeError("v339 launcher ordering invalid")
    return text


def patch_v169_text(text: str) -> str:
    old_path = '''def _execution_marker_path() -> Path:\n    return Path(os.environ.get("HEARTBEAT_MARKER_PATH", "./data/heartbeat_verified.flag"))\n\n\n'''
    new_path = '''def _execution_marker_path() -> Path:\n    return Path(\n        os.environ.get("NIJA_EXECUTION_MARKER_PATH", "")\n        or os.environ.get("HEARTBEAT_MARKER_PATH", "./data/heartbeat_verified.flag")\n    )\n\n\ndef _quarantine_authority_execution_marker() -> str:\n    """Remove only a legacy authority-origin marker from the execution path."""\n    path = _execution_marker_path()\n    if not path.exists():\n        return "missing"\n    try:\n        raw = path.read_text(encoding="utf-8").strip()\n        payload = json.loads(raw) if raw.startswith("{") else {}\n    except Exception:\n        # Unknown proof remains untouched so verification stays fail-closed.\n        return "unparseable_preserved"\n\n    source = str(payload.get("source", "") or "").strip().lower()\n    kind = str(payload.get("proof_kind", "") or "").strip().lower()\n    stage = str(payload.get("stage", "") or "").strip().upper()\n    if source not in {"heartbeat_authority_single_source", "authority_heartbeat"}:\n        return "preserved"\n    if kind not in {"", "authority_liveness"}:\n        return "preserved"\n\n    quarantine = path.with_name(path.name + ".authority-quarantined-v339")\n    try:\n        if quarantine.exists():\n            quarantine.unlink()\n        path.replace(quarantine)\n    except Exception:\n        try:\n            path.unlink()\n        except FileNotFoundError:\n            pass\n    LOGGER.warning(\n        "EXECUTION_PROOF_V339_AUTHORITY_MARKER_QUARANTINED marker=%s path=%s "\n        "source=%s proof_kind=%s stage=%s execution_proof_fabricated=false "\n        "trading_fail_closed=true",\n        MARKER,\n        path,\n        source or "missing",\n        kind or "missing",\n        stage or "missing",\n    )\n    return "quarantined"\n\n\n'''
    text = _replace_once(text, old_path, new_path, "v169 execution marker path")

    old_install = '''def install() -> bool:\n    with _LOCK:\n        surfaces_ok = _patch_execution_surfaces()\n        import_hook_ok = _install_import_reassertion_hook()\n        capital_ok = _patch_v164_publish_preseed()\n        manifest_ok = _patch_release_manifest()\n        ready = bool(surfaces_ok and import_hook_ok and capital_ok and manifest_ok)\n'''
    new_install = '''def install() -> bool:\n    with _LOCK:\n        execution_path = _execution_marker_path()\n        authority_path = _authority_marker_path()\n        if execution_path.resolve() == authority_path.resolve():\n            os.environ[_READY_FLAG] = "0"\n            LOGGER.critical(\n                "RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_FAILED marker=%s "\n                "reason=authority_execution_marker_path_collision trading_fail_closed=true",\n                MARKER,\n            )\n            return False\n        _quarantine_authority_execution_marker()\n        surfaces_ok = _patch_execution_surfaces()\n        if surfaces_ok:\n            # Legacy consumers may use HEARTBEAT_MARKER_PATH, but only after all\n            # authority writers have been redirected to the authority-only path.\n            os.environ["HEARTBEAT_MARKER_PATH"] = str(execution_path)\n        import_hook_ok = _install_import_reassertion_hook()\n        capital_ok = _patch_v164_publish_preseed()\n        manifest_ok = _patch_release_manifest()\n        ready = bool(surfaces_ok and import_hook_ok and capital_ok and manifest_ok)\n'''
    text = _replace_once(text, old_install, new_install, "v169 install ordering")
    if "NIJA_EXECUTION_MARKER_PATH" not in text or "_quarantine_authority_execution_marker()" not in text:
        raise RuntimeError("v339 v169 hardening incomplete")
    return text


def patch_v238_text(text: str) -> str:
    old = '''def _genuine_execution_marker_ready() -> tuple[bool, str]:\n    try:\n        tsm = importlib.import_module("bot.trading_state_machine")\n        verifier = getattr(tsm, "_heartbeat_verification_status", None)\n        if not callable(verifier):\n            return False, "canonical_verifier_unavailable"\n        ok, detail, _meta = verifier()\n        return bool(ok), str(detail or "verified")\n    except Exception as exc:\n        return False, f"verification_error:{type(exc).__name__}:{exc}"\n\n\n'''
    new = '''def _genuine_execution_marker_ready() -> tuple[bool, str]:\n    try:\n        if os.environ.get("NIJA_RUNTIME_EXECUTION_CAPITAL_INTEGRITY_V169_READY") != "1":\n            return False, "v169_provenance_guard_not_ready"\n        tsm = importlib.import_module("bot.trading_state_machine")\n        verifier = getattr(tsm, "_heartbeat_verification_status", None)\n        if not callable(verifier):\n            return False, "canonical_verifier_unavailable"\n        ok, detail, meta = verifier()\n        meta = dict(meta or {})\n        if not ok:\n            return False, str(detail or "execution_proof_not_ready")\n        source = str(meta.get("source", "") or "").strip().lower()\n        kind = str(meta.get("proof_kind", "") or "").strip().lower()\n        if source != "heartbeat_trade" or kind != "execution_probe":\n            return False, (\n                "v169_execution_provenance_missing:"\n                f"source={source or 'missing'}:kind={kind or 'missing'}"\n            )\n        return True, "verified_v169_execution_probe"\n    except Exception as exc:\n        return False, f"verification_error:{type(exc).__name__}:{exc}"\n\n\n'''
    text = _replace_once(text, old, new, "v238 genuine execution guard")
    if "v169_provenance_guard_not_ready" not in text or "verified_v169_execution_probe" not in text:
        raise RuntimeError("v339 v238 hardening incomplete")
    return text


def _patch_file(path: Path, patcher) -> None:
    original = path.read_text(encoding="utf-8")
    patched = patcher(original)
    if patched != original:
        path.write_text(patched, encoding="utf-8")


def main() -> int:
    _patch_file(LAUNCHER_PATH, patch_launcher_text)
    _patch_file(V169_PATH, patch_v169_text)
    _patch_file(V238_PATH, patch_v238_text)
    print(
        "EXECUTION_PROOF_STARTUP_ISOLATION_V339_SOURCE_READY "
        f"marker={MARKER} startup_order_hardened=true authority_marker_quarantine=true "
        "v238_v169_provenance_required=true execution_proof_fabricated=false "
        "forced_activation=false safety_gates_bypassed=false",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
