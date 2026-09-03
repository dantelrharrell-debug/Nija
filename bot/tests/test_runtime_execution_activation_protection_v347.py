from types import SimpleNamespace

import bot.runtime_execution_activation_protection_v347_patch as v347


def test_v347_does_not_wake_without_genuine_marker(monkeypatch):
    class V238:
        @staticmethod
        def _genuine_execution_marker_ready():
            return False, "marker_missing"

        @staticmethod
        def _wake_activation_after_genuine_marker(source):
            raise AssertionError("must not wake without genuine marker")

    real_import = v347.importlib.import_module
    monkeypatch.setattr(
        v347.importlib,
        "import_module",
        lambda name: V238 if name == "bot.runtime_heartbeat_marker_convergence_v238_patch" else real_import(name),
    )
    assert v347._wake_activation() is False


def test_v347_wakes_only_after_marker_ready(monkeypatch):
    calls = []

    class V238:
        @staticmethod
        def _genuine_execution_marker_ready():
            return True, "verified"

        @staticmethod
        def _wake_activation_after_genuine_marker(source):
            calls.append(source)
            return True

    real_import = v347.importlib.import_module
    monkeypatch.setattr(
        v347.importlib,
        "import_module",
        lambda name: V238 if name == "bot.runtime_heartbeat_marker_convergence_v238_patch" else real_import(name),
    )
    assert v347._wake_activation() is True
    assert calls == ["canonical_confirmed_fill_v347"]


def test_v347_marker_wrapper_preserves_false_result(monkeypatch):
    class V346:
        @staticmethod
        def _write_confirmed_fill_marker(*args, **kwargs):
            return False

    real_import = v347.importlib.import_module
    monkeypatch.setattr(
        v347.importlib,
        "import_module",
        lambda name: V346 if name == "bot.runtime_execution_position_readiness_v346_patch" else real_import(name),
    )
    monkeypatch.setattr(v347, "_wake_activation", lambda: (_ for _ in ()).throw(AssertionError("wake must not run")))
    assert v347._patch_v346_marker_writer() is True
    assert V346._write_confirmed_fill_marker(result={}, symbol="BTC-USD", side="buy", fill_price=0, filled_usd=0) is False


def test_v347_protection_audit_never_mutates_trackers(monkeypatch):
    class V281:
        @staticmethod
        def coverage_status():
            return {"ready": True, "protections": ("stop_loss", "take_profit", "trailing_stop")}

    real_import = v347.importlib.import_module
    monkeypatch.setattr(
        v347.importlib,
        "import_module",
        lambda name: V281 if name == "bot.runtime_all_account_position_exit_coverage_v281_patch" else real_import(name),
    )
    assert v347._audit_protective_coverage() is True
