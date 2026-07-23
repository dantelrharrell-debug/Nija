from __future__ import annotations

import sys
from types import ModuleType

import bot.okx_order_wrapper_stability_patch as stability


def _fake_patch_modules():
    instid = ModuleType(stability._INSTID_CANONICAL)
    final = ModuleType(stability._FINAL_CANONICAL)
    instid._ORDER_WRAP_ATTR = stability._INSTID_ATTR
    final._ORDER_WRAP_ATTR = stability._FINAL_ATTR
    install_calls = {"instid": 0, "final": 0}

    def candidate_classes(module):
        cls = getattr(module, "OKXBroker", None)
        return [cls] if isinstance(cls, type) else []

    instid._candidate_order_classes = candidate_classes
    final._candidate_order_classes = candidate_classes

    def final_wrap(cls, _module_name):
        changed = False
        for method_name in stability._ORDER_METHODS:
            current = getattr(cls, method_name, None)
            if not callable(current) or getattr(current, stability._FINAL_ATTR, False):
                continue
            # Mirror the legacy defect: one wrapper layer was discarded.
            base = getattr(current, "__wrapped__", current)

            def final_order(self, *args, __base=base, **kwargs):
                return __base(self, *args, **kwargs)

            setattr(final_order, stability._FINAL_ATTR, True)
            final_order.__wrapped__ = base
            setattr(cls, method_name, final_order)
            changed = True
        return changed

    def instid_wrap(cls, _module_name):
        changed = False
        for method_name in stability._ORDER_METHODS:
            current = getattr(cls, method_name, None)
            if not callable(current) or getattr(current, stability._INSTID_ATTR, False):
                continue

            def instid_order(self, symbol, side, quantity, *args, __current=current, **kwargs):
                normalized = str(symbol).upper().replace("/", "-")
                if normalized.endswith("-USD"):
                    normalized = normalized[:-4] + "-USDT"
                return __current(self, normalized, side, quantity, *args, **kwargs)

            setattr(instid_order, stability._INSTID_ATTR, True)
            instid_order.__wrapped__ = current
            setattr(cls, method_name, instid_order)
            changed = True
        return changed

    instid._wrap_order_class = instid_wrap
    final._wrap_order_class = final_wrap

    def patch_module_factory(module):
        def patch_module(target):
            changed = False
            for cls in candidate_classes(target):
                changed = bool(module._wrap_order_class(cls, target.__name__)) or changed
            return changed

        return patch_module

    instid._patch_module = patch_module_factory(instid)
    final._patch_module = patch_module_factory(final)
    instid.install_import_hook = lambda: install_calls.__setitem__("instid", install_calls["instid"] + 1)
    final.install_import_hook = lambda: install_calls.__setitem__("final", install_calls["final"] + 1)
    return instid, final, install_calls


def _prepare_okx_runtime(monkeypatch):
    calls = []

    class OKXBroker:
        def place_market_order(self, symbol, side, quantity, *args, **kwargs):
            calls.append((symbol, side, quantity))
            return {"status": "ok", "symbol": symbol}

    target = ModuleType("bot.broker_manager")
    target.OKXBroker = OKXBroker
    instid, final, install_calls = _fake_patch_modules()
    mapping = {
        stability._INSTID_CANONICAL: instid,
        stability._FINAL_CANONICAL: final,
    }
    real_import = stability.importlib.import_module
    monkeypatch.setattr(
        stability.importlib,
        "import_module",
        lambda name: mapping.get(name) or real_import(name),
    )
    monkeypatch.setitem(sys.modules, "bot.broker_manager", target)
    monkeypatch.setitem(sys.modules, "broker_manager", target)
    monkeypatch.setattr(stability, "_PATCH_INSTALLERS_READY", False)
    return target, calls, install_calls


def test_two_okx_safety_layers_are_preserved_and_idempotent(monkeypatch):
    target, calls, install_calls = _prepare_okx_runtime(monkeypatch)

    ready, details = stability._ensure_okx_wrappers()
    assert ready is True
    first = target.OKXBroker.place_market_order
    instid, instid_cycle, _ = stability._chain_has_attr(first, stability._INSTID_ATTR)
    final, final_cycle, _ = stability._chain_has_attr(first, stability._FINAL_ATTR)
    assert instid is True and final is True
    assert instid_cycle is False and final_cycle is False
    assert "instid=True" in str(details)
    assert "final=True" in str(details)

    result = target.OKXBroker().place_market_order("BTC/USD", "buy", 10)
    assert result["status"] == "ok"
    assert calls == [("BTC-USDT", "buy", 10)]

    ready, _ = stability._ensure_okx_wrappers()
    assert ready is True
    assert target.OKXBroker.place_market_order is first
    assert install_calls == {"instid": 1, "final": 1}
    assert sys.modules[stability._INSTID_ALIAS] is sys.modules[stability._INSTID_CANONICAL]
    assert sys.modules[stability._FINAL_ALIAS] is sys.modules[stability._FINAL_CANONICAL]


def test_late_okx_method_replacement_is_healed_without_chain_growth(monkeypatch):
    target, calls, _install_calls = _prepare_okx_runtime(monkeypatch)
    ready, _ = stability._ensure_okx_wrappers()
    assert ready is True

    def late_replacement(self, symbol, side, quantity, *args, **kwargs):
        calls.append(("late", symbol, side, quantity))
        return {"status": "late"}

    target.OKXBroker.place_market_order = late_replacement
    ready, _ = stability._ensure_okx_wrappers()
    assert ready is True
    repaired = target.OKXBroker.place_market_order
    instid, instid_cycle, instid_depth = stability._chain_has_attr(repaired, stability._INSTID_ATTR)
    final, final_cycle, final_depth = stability._chain_has_attr(repaired, stability._FINAL_ATTR)
    assert instid is True and final is True
    assert instid_cycle is False and final_cycle is False
    assert max(instid_depth, final_depth) <= 2

    target.OKXBroker().place_market_order("ETH/USD", "sell", 5)
    assert calls[-1] == ("late", "ETH-USDT", "sell", 5)

    same = target.OKXBroker.place_market_order
    ready, _ = stability._ensure_okx_wrappers()
    assert ready is True
    assert target.OKXBroker.place_market_order is same


def test_pretrade_risk_is_imported_patched_and_alias_bound_once(monkeypatch):
    pretrade = ModuleType(stability._PRETRADE_CANONICAL)
    pretrade.PreTradeRiskEngine = type("PreTradeRiskEngine", (), {"assess": lambda self, **kwargs: None})
    pretrade.PreTradeRiskDecision = type("PreTradeRiskDecision", (), {})

    risk = ModuleType(stability._RISK_CANONICAL)
    risk._STATE = {"downstream": True, "pipeline": True, "pretrade": False, "taxonomy": True}
    install_calls = []

    def patch_pretrade(module):
        assert module is pretrade
        risk._STATE["pretrade"] = True
        return True

    risk._install_on_pre_trade_risk_engine = patch_pretrade
    risk.install_import_hook = lambda: install_calls.append("install")
    mapping = {
        stability._PRETRADE_CANONICAL: pretrade,
        stability._RISK_CANONICAL: risk,
    }
    real_import = stability.importlib.import_module
    monkeypatch.setattr(
        stability.importlib,
        "import_module",
        lambda name: mapping.get(name) or real_import(name),
    )
    monkeypatch.setattr(stability, "_RISK_INSTALLER_READY", False)

    ready, details = stability._ensure_pretrade_risk()
    assert ready is True
    assert "'pretrade': True" in details
    ready, _ = stability._ensure_pretrade_risk()
    assert ready is True
    assert install_calls == ["install"]
    assert sys.modules[stability._PRETRADE_ALIAS] is pretrade
    assert sys.modules[stability._RISK_ALIAS] is risk
    assert stability.os.environ["NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_READY"] == "1"


def test_import_hook_scope_is_exact_not_all_broker_or_okx_modules():
    assert stability._narrow_interesting("bot.broker_manager") is True
    assert stability._narrow_interesting("broker_integration") is True
    assert stability._narrow_interesting("some_unrelated_broker_module") is False
    assert stability._narrow_interesting("random_okx_helper") is False
