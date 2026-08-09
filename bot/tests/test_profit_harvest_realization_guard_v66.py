from __future__ import annotations

import importlib
import types
import unittest


class _State:
    def __init__(self) -> None:
        self.harvestable_balance_usd = 0.0
        self.cumulative_harvested_usd = 0.0
        self.cumulative_harvested_pct = 0.0
        self.harvest_log = []
        self.last_harvested_tier = "NONE"
        self.last_updated = ""


class _Decision:
    def __init__(self, *, amount=0.0, floor_hit=False) -> None:
        self.harvest_triggered = amount > 0.0
        self.harvest_amount_usd = amount
        self.floor_hit = floor_hit
        self.message = "legacy"


class _ProfitEngine:
    def __init__(self, available=100.0) -> None:
        self.available = available
        self.calls = []

    def harvest_profits(self, amount=None, note=""):
        requested = self.available if amount is None else float(amount)
        actual = min(requested, self.available)
        self.available -= actual
        self.calls.append((actual, note))
        return actual


class ProfitHarvestRealizationGuardV66Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.patch = importlib.import_module("bot.profit_harvest_realization_guard_v66_patch")

    def _fake_module(self, *, floor_hit=False):
        fake = types.ModuleType("profit_harvest_v66_fake")
        engine = _ProfitEngine(available=100.0)

        class Layer:
            def __init__(self) -> None:
                import threading
                self._lock = threading.RLock()
                self._positions = {"BTC-USD": _State()}

            def _save_state(self):
                return None

            def _route_to_profit_engine(self, symbol, amount_usd, note=""):
                return engine.harvest_profits(amount=amount_usd, note=note)

            def process_price_update(self, symbol, current_price):
                state = self._positions[symbol]
                state.harvestable_balance_usd += 10.0
                state.cumulative_harvested_usd += 10.0
                state.cumulative_harvested_pct += 1.0
                state.harvest_log.append({"note": "legacy-tier", "harvest_usd": 10.0})
                state.last_harvested_tier = "TIER_1"
                if floor_hit:
                    self._route_to_profit_engine(symbol, state.harvestable_balance_usd, note="floor")
                    state.harvestable_balance_usd = 0.0
                return _Decision(amount=10.0, floor_hit=floor_hit)

            def partial_harvest(self, symbol, fraction=1.0, note=""):
                state = self._positions[symbol]
                amount = state.harvestable_balance_usd * fraction
                state.harvestable_balance_usd -= amount
                return self._route_to_profit_engine(symbol, amount, note=note)

        fake.ProfitHarvestLayer = Layer
        fake.HarvestEvent = None
        fake.get_portfolio_profit_engine = lambda: engine
        self.patch._patch(fake)
        return Layer(), engine

    def test_tier_upgrade_stays_unrealized_until_fill_proof(self) -> None:
        layer, engine = self._fake_module()
        decision = layer.process_price_update("BTC-USD", 101.0)
        state = layer._positions["BTC-USD"]

        self.assertFalse(decision.harvest_triggered)
        self.assertEqual(decision.harvest_amount_usd, 0.0)
        self.assertEqual(state.harvestable_balance_usd, 10.0)
        self.assertEqual(state.cumulative_harvested_usd, 0.0)
        self.assertEqual(state.cumulative_harvested_pct, 0.0)
        self.assertEqual(engine.calls, [])
        self.assertIn("UNREALIZED_CANDIDATE", state.harvest_log[-1]["note"])

    def test_floor_hit_does_not_book_virtual_profit(self) -> None:
        layer, engine = self._fake_module(floor_hit=True)
        layer.process_price_update("BTC-USD", 101.0)
        state = layer._positions["BTC-USD"]

        self.assertEqual(engine.calls, [])
        self.assertEqual(state.harvestable_balance_usd, 10.0)
        self.assertEqual(state.cumulative_harvested_usd, 0.0)

    def test_legacy_partial_harvest_is_fail_closed(self) -> None:
        layer, engine = self._fake_module()
        layer.process_price_update("BTC-USD", 101.0)
        amount = layer.partial_harvest("BTC-USD", fraction=0.5)

        self.assertEqual(amount, 0.0)
        self.assertEqual(layer._positions["BTC-USD"].harvestable_balance_usd, 10.0)
        self.assertEqual(engine.calls, [])

    def test_confirmed_fill_realizes_only_available_candidate(self) -> None:
        layer, engine = self._fake_module()
        layer.process_price_update("BTC-USD", 101.0)
        actual = layer.confirm_realized_harvest(
            "BTC-USD",
            25.0,
            broker_fill_id="fill-123",
            broker_name="coinbase",
            account_id="platform",
        )
        state = layer._positions["BTC-USD"]

        self.assertEqual(actual, 10.0)
        self.assertEqual(state.harvestable_balance_usd, 0.0)
        self.assertEqual(state.cumulative_harvested_usd, 10.0)
        self.assertEqual(len(engine.calls), 1)
        self.assertIn("fill_id=fill-123", engine.calls[0][1])
        self.assertIn("REALIZED_CONFIRMED", state.harvest_log[-1]["note"])

    def test_fill_id_is_mandatory(self) -> None:
        layer, _engine = self._fake_module()
        layer.process_price_update("BTC-USD", 101.0)
        with self.assertRaises(ValueError):
            layer.confirm_realized_harvest(
                "BTC-USD",
                5.0,
                broker_fill_id="",
            )


if __name__ == "__main__":
    unittest.main()
