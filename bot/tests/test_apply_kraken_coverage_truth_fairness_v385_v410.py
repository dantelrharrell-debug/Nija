from __future__ import annotations

from pathlib import Path

from scripts import apply_kraken_coverage_truth_fairness_v385 as patcher


def _fixture_source() -> str:
    return '''from __future__ import annotations\n\nimport logging\nfrom typing import Any, Dict, Tuple\n\nLOGGER = logging.getLogger("test")\n\ndef _private_call(broker):\n    return broker\n\ndef _log_fetch_failed(account, reason):\n    return None\n\ndef fetch_margin_positions(broker: Any, *, account: Any = "", force: bool = False) -> Tuple[bool, Dict[str, Dict[str, Any]], str]:\n    key = str(account)\n    call = _private_call(broker)\n    try:\n        payload = call("OpenPositions", {"docalcs": "true"})\n    except Exception as exc:\n        reason = f"openpositions_exception:{type(exc).__name__}"\n        _log_fetch_failed(key, reason)\n        return False, {}, reason\n    return True, {}, "ok"\n'''


def test_v410_injection_is_idempotent_and_compiles(tmp_path: Path, monkeypatch):
    target = tmp_path / "v366.py"
    target.write_text(_fixture_source(), encoding="utf-8")
    monkeypatch.setattr(patcher, "V366", target)

    assert patcher.patch_v366_openpositions_diagnostics_v410() is True
    assert patcher.patch_v366_openpositions_diagnostics_v410() is False

    rendered = target.read_text(encoding="utf-8")
    assert rendered.count("KRAKEN_OPENPOSITIONS_DIAGNOSTIC_V410") == 1
    assert "message_redacted=true" in rendered
    assert "return_value_unchanged=true" in rendered
    assert 'reason = f"openpositions_exception:{type(exc).__name__}"' in rendered
    compile(rendered, str(target), "exec")


def test_v410_classifier_categories_are_bounded(tmp_path: Path, monkeypatch):
    target = tmp_path / "v366.py"
    target.write_text(_fixture_source(), encoding="utf-8")
    monkeypatch.setattr(patcher, "V366", target)
    assert patcher.patch_v366_openpositions_diagnostics_v410() is True

    namespace: dict[str, object] = {}
    exec(compile(target.read_text(encoding="utf-8"), str(target), "exec"), namespace)
    classifier = namespace["_classify_openpositions_exception_v410"]

    assert classifier(Exception("EAPI:Permission denied secret-token")) == "api_permission_denied"
    assert classifier(Exception("Kraken nonce readiness gate blocked API call")) == "nonce_authority_unready"
    assert classifier(Exception("EAPI:Invalid nonce")) == "kraken_invalid_nonce"
    assert classifier(Exception("connection reset by peer")) == "transport_failure"
    assert classifier(Exception("opaque SECRET-DO-NOT-LOG")) == "unclassified_exception"
