from __future__ import annotations

from types import ModuleType

import runtime_convergence_v15_patch as patch


def test_chain_contains_finds_nested_marker() -> None:
    def base() -> None:
        return None

    def outer() -> None:
        return None

    setattr(base, "_marker", True)
    setattr(outer, "__wrapped__", base)

    found, cycle, depth = patch._chain_contains(outer, "_marker")

    assert found is True
    assert cycle is False
    assert depth == 1


def test_chain_contains_detects_cycle() -> None:
    def first() -> None:
        return None

    def second() -> None:
        return None

    setattr(first, "__wrapped__", second)
    setattr(second, "__wrapped__", first)

    found, cycle, depth = patch._chain_contains(first, "_missing_marker")

    assert found is False
    assert cycle is True
    assert depth >= 1


def test_guard_class_patcher_prevents_duplicate_wrapper_install() -> None:
    module = ModuleType("fake_okx_patch")
    calls = {"count": 0}

    def install_wrapper(cls: type) -> bool:
        current = getattr(cls, "submit")
        if getattr(current, "_repair_marker", False):
            return False
        calls["count"] += 1

        def wrapped(*args, **kwargs):
            return current(*args, **kwargs)

        setattr(wrapped, "_repair_marker", True)
        setattr(wrapped, "__wrapped__", current)
        setattr(cls, "submit", wrapped)
        return True

    setattr(module, "install_wrapper", install_wrapper)

    class Broker:
        @staticmethod
        def submit() -> str:
            return "ok"

    assert module.install_wrapper(Broker) is True
    first_wrapped = Broker.submit

    def later_outer(*args, **kwargs):
        return first_wrapped(*args, **kwargs)

    setattr(later_outer, "__wrapped__", first_wrapped)
    Broker.submit = staticmethod(later_outer)

    assert patch._guard_class_patcher(
        module,
        "install_wrapper",
        ("submit",),
        "_repair_marker",
    ) is True

    assert module.install_wrapper(Broker) is False
    assert calls["count"] == 1
    assert getattr(Broker.submit, "_repair_marker", False) is True


def test_activation_stays_closed_when_release_is_not_ready() -> None:
    assert patch._activation_step(False) is False
