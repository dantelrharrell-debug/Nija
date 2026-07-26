from __future__ import annotations

import importlib


def _module():
    return importlib.import_module("coinbase_authenticated_connect_recovery_patch")


def test_wrapper_chain_detects_nested_recovery_marker():
    module = _module()

    def original(self):
        return True

    def recovery(self):
        return original(self)

    setattr(recovery, module._PATCH_ATTR, True)
    recovery.__wrapped__ = original

    def outer(self):
        return recovery(self)

    outer.__wrapped__ = recovery

    assert module._wrapper_chain_has_patch(outer) is True


def test_patch_class_does_not_duplicate_nested_recovery_wrapper():
    module = _module()

    def original(self):
        return True

    def recovery(self):
        return original(self)

    setattr(recovery, module._PATCH_ATTR, True)
    recovery.__wrapped__ = original

    def outer(self):
        return recovery(self)

    outer.__wrapped__ = recovery

    class CoinbaseBroker:
        connect = outer

    before = CoinbaseBroker.connect
    assert module._patch_class(CoinbaseBroker) is True
    assert CoinbaseBroker.connect is before


def test_wrapper_chain_cycle_is_safe():
    module = _module()

    def outer(self):
        return True

    outer.__wrapped__ = outer
    assert module._wrapper_chain_has_patch(outer) is False
