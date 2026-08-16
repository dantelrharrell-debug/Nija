from __future__ import annotations

import ast
from pathlib import Path


def _load_bot_functions():
    path = Path(__file__).resolve().parents[1] / "bot.py"
    tree = ast.parse(path.read_text())
    wanted = {"_canonical_fast_import", "_install_guards"}
    body = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    body += [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    module = ast.Module(body=body, type_ignores=[])
    ns: dict[str, object] = {}
    exec(compile(module, str(path), "exec"), ns)
    return ns


def test_canonical_fast_import_does_not_call_wrapped_import_module(monkeypatch):
    ns = _load_bot_functions()
    import importlib

    def exploding_import_module(*args, **kwargs):
        raise AssertionError("wrapped importlib.import_module must not be used")

    monkeypatch.setattr(importlib, "import_module", exploding_import_module)
    module = ns["_canonical_fast_import"]("math")
    assert module.__name__ == "math"


def test_install_guards_uses_canonical_loader_in_fast_mode(monkeypatch):
    ns = _load_bot_functions()
    calls: list[str] = []

    class FakeModule:
        @staticmethod
        def install():
            calls.append("install")
            return True

    def fake_fast_import(name: str):
        calls.append(name)
        return FakeModule

    ns["_canonical_fast_import"] = fake_fast_import
    ok = ns["_install_guards"]((("bot.fake_guard", "FAKE"),), mode="canonical_fast")
    assert ok is True
    assert calls == ["bot.fake_guard", "install"]
