"""Regression tests for capital-authority publisher alias convergence v230."""
from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from functools import wraps
from types import ModuleType
from unittest.mock import patch

import bot.runtime_capital_authority_alias_v230_patch as v230
import bot.runtime_zero_balance_completeness_v209_patch as v209


@dataclass(frozen=True)
class _Snapshot:
    real_capital: float
    broker_balances: dict[str, float]
    broker_count: int
    expected_brokers: int = 3


def _authority_module(name: str) -> tuple[ModuleType, type]:
    module = ModuleType(name)

    class CapitalAuthority:
        def __init__(self) -> None:
            self.seen = None

        def publish_snapshot(self, snapshot, writer_id):
            self.seen = snapshot
            return True

    module.CapitalAuthority = CapitalAuthority
    return module, CapitalAuthority


class CapitalAuthorityAliasV230Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = _Snapshot(
            real_capital=345.97,
            broker_balances={"kraken": 252.76, "coinbase": 93.21},
            broker_count=2,
        )

    def test_distinct_authority_alias_classes_are_both_patched(self) -> None:
        canonical, canonical_cls = _authority_module("bot.capital_authority")
        alias, alias_cls = _authority_module("capital_authority")
        with patch.dict(sys.modules, {"bot.capital_authority": canonical, "capital_authority": alias}, clear=False):
            patched, loaded = v230._patch_loaded_aliases()
        self.assertEqual(loaded, 2)
        self.assertEqual(patched, 2)
        self.assertTrue(v230._is_direct_wrapper(canonical_cls.publish_snapshot))
        self.assertTrue(v230._is_direct_wrapper(alias_cls.publish_snapshot))

    def test_duplicate_class_identity_is_deduplicated(self) -> None:
        canonical, canonical_cls = _authority_module("bot.capital_authority")
        alias = ModuleType("capital_authority")
        alias.CapitalAuthority = canonical_cls
        with patch.dict(sys.modules, {"bot.capital_authority": canonical, "capital_authority": alias}, clear=False):
            rows = v230._loaded_authority_classes()
        self.assertEqual(len(rows), 1)

    def test_noncanonical_alias_publish_uses_v209_augmentation(self) -> None:
        alias, alias_cls = _authority_module("capital_authority")
        canonical, _ = _authority_module("bot.capital_authority")
        augmented = _Snapshot(
            real_capital=self.snapshot.real_capital,
            broker_balances={**self.snapshot.broker_balances, "okx": 0.0},
            broker_count=3,
        )
        with patch.dict(sys.modules, {"bot.capital_authority": canonical, "capital_authority": alias}, clear=False):
            with patch.object(v209, "_augment_snapshot", return_value=(augmented, ("okx",))):
                self.assertTrue(v230._patch_class("capital_authority", alias_cls))
                authority = alias_cls()
                self.assertTrue(authority.publish_snapshot(self.snapshot, "writer"))
        self.assertEqual(authority.seen.broker_count, 3)
        self.assertEqual(authority.seen.broker_balances["okx"], 0.0)
        self.assertEqual(authority.seen.real_capital, self.snapshot.real_capital)

    def test_outer_wraps_marker_copy_is_reanchored_before_completeness_gate(self) -> None:
        """A replayed outer gate must not hide V230 behind a copied marker."""
        alias, alias_cls = _authority_module("capital_authority")
        augmented = _Snapshot(
            real_capital=self.snapshot.real_capital,
            broker_balances={**self.snapshot.broker_balances, "okx": 0.0},
            broker_count=3,
        )
        with patch.object(v209, "_augment_snapshot", return_value=(augmented, ("okx",))):
            self.assertTrue(v230._patch_class("capital_authority", alias_cls))
            v230_inner = alias_cls.publish_snapshot

            @wraps(v230_inner)
            def replayed_completeness_gate(self, snapshot, writer_id):
                if int(getattr(snapshot, "broker_count", 0) or 0) < 3:
                    return False
                return v230_inner(self, snapshot, writer_id)

            # functools.wraps copied V230's marker even though this function is
            # not V230's augmentation boundary. This reproduces production.
            alias_cls.publish_snapshot = replayed_completeness_gate
            self.assertTrue(getattr(alias_cls.publish_snapshot, v230._PATCH_ATTR, False))
            self.assertFalse(v230._is_direct_wrapper(alias_cls.publish_snapshot))

            # Reassertion must wrap outside the replayed gate so the 2/3 raw
            # snapshot becomes a truthful 3/3 snapshot before the gate checks it.
            self.assertTrue(v230._patch_class("capital_authority", alias_cls))
            self.assertTrue(v230._is_direct_wrapper(alias_cls.publish_snapshot))
            authority = alias_cls()
            self.assertTrue(authority.publish_snapshot(self.snapshot, "writer"))

        self.assertEqual(authority.seen.broker_count, 3)
        self.assertEqual(authority.seen.broker_balances["okx"], 0.0)
        self.assertEqual(authority.seen.real_capital, self.snapshot.real_capital)

    def test_direct_wrapper_reassert_is_idempotent(self) -> None:
        alias, alias_cls = _authority_module("capital_authority")
        self.assertTrue(v230._patch_class("capital_authority", alias_cls))
        first = alias_cls.publish_snapshot
        self.assertTrue(v230._patch_class("capital_authority", alias_cls))
        self.assertIs(alias_cls.publish_snapshot, first)
        self.assertTrue(v230._is_direct_wrapper(alias_cls.publish_snapshot))

    def test_no_addition_leaves_snapshot_unchanged(self) -> None:
        alias, alias_cls = _authority_module("capital_authority")
        with patch.object(v209, "_augment_snapshot", return_value=(self.snapshot, ())):
            self.assertTrue(v230._patch_class("capital_authority", alias_cls))
            authority = alias_cls()
            self.assertTrue(authority.publish_snapshot(self.snapshot, "writer"))
        self.assertIs(authority.seen, self.snapshot)

    def test_augmentation_failure_fails_closed_with_original_snapshot(self) -> None:
        alias, alias_cls = _authority_module("capital_authority")
        with patch.object(v209, "_augment_snapshot", side_effect=RuntimeError("bad provenance")):
            self.assertTrue(v230._patch_class("capital_authority", alias_cls))
            authority = alias_cls()
            self.assertTrue(authority.publish_snapshot(self.snapshot, "writer"))
        self.assertIs(authority.seen, self.snapshot)


if __name__ == "__main__":
    unittest.main()
