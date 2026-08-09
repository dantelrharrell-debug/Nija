from __future__ import annotations

import importlib
import os
import types
import unittest
from unittest.mock import patch


class AdaptiveProfitExitV74Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("bot.adaptive_profit_exit_v74_patch")
        self.mod._POSITIONS.clear()
        self.mod._STATS.clear()

    def _universal(self, base_trigger):
        module = types.ModuleType("universal_exit_v74_fake")

        class AutoExit:
            @staticmethod
            def _sym(value):
                return str(value or "").upper()

            @staticmethod
            def _entry_price(pos):
                return float(pos.get("entry_price", 0.0) or 0.0)

            @staticmethod
            def _quantity(pos):
                return float(pos.get("quantity", 0.0) or 0.0)

            @staticmethod
            def _side(value, pos):
                return str(value or pos.get("side") or "long").lower()

            @staticmethod
            def _get(mapping, *keys, default=None):
                for key in keys:
                    if key in mapping and mapping[key] is not None:
                        return mapping[key]
                return default

        module.auto_exit = AutoExit
        module._trigger = base_trigger
        return module

    def _broker(self):
        return types.SimpleNamespace(broker_name="coinbase", account_id="acct-a")

    def _pos(self, **extra):
        base = {
            "symbol": "BTC-USD",
            "position_id": "p1",
            "account_id": "acct-a",
            "entry_price": 100.0,
            "quantity": 1.0,
            "side": "long",
            "market_regime": "bull_trending",
            "regime_confidence": 0.90,
            "atr_pct": 0.01,
        }
        base.update(extra)
        return base

    def test_strong_trend_profit_floor_arms_instead_of_immediate_tp(self) -> None:
        universal = self._universal(lambda broker, pos, market: (True, "net_profit_target", 101.0))
        with patch.object(self.mod.v68, "_floors", return_value=(100.5, 101.0, {"entry": 100.0, "short": False})):
            with patch.object(self.mod.v68, "_reason_kind", return_value="profit"):
                with patch.object(self.mod.v68, "_meets", side_effect=lambda market, target, short: market >= target):
                    self.mod._patch_universal(universal)
                    hit, reason, target = universal._trigger(self._broker(), self._pos(), 102.0)
        self.assertFalse(hit)
        self.assertEqual(reason, "")
        self.assertEqual(target, 0.0)
        self.assertTrue(self.mod._is_armed(universal, self._broker(), self._pos()))

    def test_trailing_giveback_exits_after_peak(self) -> None:
        universal = self._universal(lambda broker, pos, market: (True, "net_profit_target", 101.0))
        with patch.object(self.mod.v68, "_floors", return_value=(100.5, 101.0, {"entry": 100.0, "short": False})):
            with patch.object(self.mod.v68, "_reason_kind", return_value="profit"):
                with patch.object(self.mod.v68, "_meets", side_effect=lambda market, target, short: market >= target):
                    with patch.object(self.mod, "_trail_pct", return_value=0.02):
                        self.mod._patch_universal(universal)
                        broker = self._broker()
                        pos = self._pos()
                        self.assertFalse(universal._trigger(broker, pos, 105.0)[0])
                        hit, reason, _ = universal._trigger(broker, pos, 102.8)
        self.assertTrue(hit)
        self.assertEqual(reason, "adaptive_volatility_trailing_profit")

    def test_regime_deterioration_banks_profit_after_arming(self) -> None:
        universal = self._universal(lambda broker, pos, market: (True, "net_profit_target", 101.0))
        with patch.object(self.mod.v68, "_floors", return_value=(100.5, 101.0, {"entry": 100.0, "short": False})):
            with patch.object(self.mod.v68, "_reason_kind", return_value="profit"):
                with patch.object(self.mod.v68, "_meets", side_effect=lambda market, target, short: market >= target):
                    self.mod._patch_universal(universal)
                    broker = self._broker()
                    pos = self._pos()
                    self.assertFalse(universal._trigger(broker, pos, 103.0)[0])
                    pos["market_regime"] = "ranging"
                    pos["regime_confidence"] = 0.90
                    hit, reason, _ = universal._trigger(broker, pos, 101.5)
        self.assertTrue(hit)
        self.assertEqual(reason, "adaptive_regime_profit_exit")

    def test_protective_exit_is_never_delayed(self) -> None:
        universal = self._universal(lambda broker, pos, market: (True, "stop_loss", 98.0))
        with patch.object(self.mod.v68, "_reason_kind", return_value="protective"):
            self.mod._patch_universal(universal)
            self.assertEqual(universal._trigger(self._broker(), self._pos(), 97.5), (True, "stop_loss", 98.0))

    def test_learning_is_sample_gated_and_bounded(self) -> None:
        universal = self._universal(lambda broker, pos, market: (False, "", 0.0))
        broker = self._broker()
        pos = self._pos()
        regime = "bull_trending"
        self.assertEqual(self.mod._learning_factor(universal, broker, pos, regime), 1.0)
        key = self.mod._scope_key(universal, broker, pos, regime)
        self.mod._STATS[key] = {"trades": 30.0, "wins": 10.0, "total_pnl": -30.0}
        self.assertEqual(self.mod._learning_factor(universal, broker, pos, regime), 0.90)
        self.mod._STATS[key] = {"trades": 30.0, "wins": 22.0, "total_pnl": 60.0}
        self.assertEqual(self.mod._learning_factor(universal, broker, pos, regime), 1.10)

    def test_confirmed_exit_updates_realized_stats_only(self) -> None:
        universal = self._universal(lambda broker, pos, market: (False, "", 0.0))
        broker = self._broker()
        pos = self._pos()
        self.mod.record_confirmed_exit(universal, broker, pos, fill_price=103.0, fee=0.5)
        key = self.mod._scope_key(universal, broker, pos, "bull_trending")
        self.assertEqual(self.mod._STATS[key]["trades"], 1.0)
        self.assertEqual(self.mod._STATS[key]["wins"], 1.0)
        self.assertAlmostEqual(self.mod._STATS[key]["total_pnl"], 2.5)


if __name__ == "__main__":
    unittest.main()
