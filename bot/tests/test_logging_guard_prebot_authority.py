from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType


def test_logging_guard_acquires_prebot_authority_before_repairs(monkeypatch) -> None:
    calls: list[str] = []
    fake = ModuleType("prebot_writer_authority_fail_closed")

    def install():
        calls.append("authority")
        os.environ["NIJA_PREBOT_WRITER_AUTHORITY_READY"] = "1"
        return object()

    fake.install = install  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "prebot_writer_authority_fail_closed", fake)
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.delenv("NIJA_PREBOT_WRITER_AUTHORITY_FORCE", raising=False)

    path = Path(__file__).resolve().parents[1] / "logging_format_guard_patch.py"
    spec = importlib.util.spec_from_file_location("test_logging_guard_prebot", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert calls == ["authority"]
    assert os.environ["NIJA_PREBOT_WRITER_AUTHORITY_READY"] == "1"
    assert "NIJA_PREBOT_WRITER_AUTHORITY_FORCE" not in os.environ


def test_logging_guard_skips_prebot_authority_outside_live_mode(monkeypatch) -> None:
    calls: list[str] = []
    fake = ModuleType("prebot_writer_authority_fail_closed")

    def install():
        calls.append("authority")
        return object()

    fake.install = install  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "prebot_writer_authority_fail_closed", fake)
    monkeypatch.delenv("LIVE_CAPITAL_VERIFIED", raising=False)
    monkeypatch.setenv("DRY_RUN_MODE", "true")
    monkeypatch.setenv("PAPER_MODE", "false")

    path = Path(__file__).resolve().parents[1] / "logging_format_guard_patch.py"
    spec = importlib.util.spec_from_file_location("test_logging_guard_nonlive", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert calls == []
