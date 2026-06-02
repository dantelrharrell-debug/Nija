import unittest

from bot.observability_dashboard import MetricCollector


class TestLiveDispatchTriageGateInference(unittest.TestCase):
    def test_classify_gate_reason_tokens(self):
        self.assertEqual(
            MetricCollector._classify_gate_reason("confidence_below_threshold"),
            "signal_confidence_thresholds",
        )
        self.assertEqual(
            MetricCollector._classify_gate_reason("volatility_explosion_long"),
            "adx_volatility_gating",
        )
        self.assertEqual(
            MetricCollector._classify_gate_reason("market_quality_gate:0.12"),
            "orderbook_liquidity_filters",
        )
        self.assertEqual(
            MetricCollector._classify_gate_reason("shadow-only"),
            "exploration_shadow_mode",
        )
        self.assertEqual(
            MetricCollector._classify_gate_reason("Balance $4.00 below minimum $5.00"),
            "capital_minimum_balance",
        )

    def test_infer_signal_gate_from_funnel_aggregate(self):
        signal_payload = {
            "available": True,
            "aggregate": {
                "signals_seen": 10,
                "confidence_pass": 10,
                "adx_pass": 0,
                "volume_pass": 0,
                "ai_gate_pass": 0,
            },
        }
        compiler_payload = {"available": True, "rejection_reasons": {}}
        inferred = MetricCollector._infer_signal_gate_blocker(signal_payload, compiler_payload)
        self.assertEqual(inferred, "adx_volatility_gating")

    def test_infer_signal_gate_prefers_compiler_rejection_reasons(self):
        signal_payload = {"available": True, "aggregate": {}}
        compiler_payload = {
            "available": True,
            "rejection_reasons": {"k_gate:confidence_below_threshold": 3},
        }
        inferred = MetricCollector._infer_signal_gate_blocker(signal_payload, compiler_payload)
        self.assertEqual(inferred, "signal_confidence_thresholds")

    def test_infer_execution_gate_from_trace_rejection_reason(self):
        traces = [
            {
                "status": "rejected",
                "terminal_reason": "cooldown_window_active",
                "stages": {},
            }
        ]
        inferred = MetricCollector._infer_trace_gate_blocker(traces)
        self.assertEqual(inferred, "cooldown_windows")

    def test_resolve_first_blocking_gate_uses_pipeline_when_readiness_passed(self):
        blocker = MetricCollector._resolve_first_blocking_gate(
            lifecycle_phase="LIVE",
            runtime_state_payload={
                "available": True,
                "trading_state": "LIVE_ACTIVE",
                "activation_committed": True,
            },
            readiness_proof_payload={
                "available": True,
                "first_blocking_gate": "none",
            },
            decision_payload={
                "available": True,
                "allowed": True,
                "decision": {},
            },
            validator_trace_payload={"available": False},
            pipeline_payload={
                "available": True,
                "stage_counts": {
                    "signals_generated": 8,
                    "signals_approved": 0,
                    "risk_passed": 0,
                    "execution_attempted": 0,
                    "orders_routed": 0,
                },
            },
            inferred_signal_gate="exploration_shadow_mode",
            inferred_execution_gate=None,
        )
        self.assertEqual(blocker, "LIVE:strategy:exploration_shadow_mode")

    def test_resolve_first_blocking_gate_labels_risk_stage_before_execution(self):
        blocker = MetricCollector._resolve_first_blocking_gate(
            lifecycle_phase="LIVE",
            runtime_state_payload={
                "available": True,
                "trading_state": "LIVE_ACTIVE",
                "activation_committed": True,
            },
            readiness_proof_payload={
                "available": True,
                "first_blocking_gate": "none",
            },
            decision_payload={
                "available": True,
                "allowed": True,
                "decision": {},
            },
            validator_trace_payload={"available": False},
            pipeline_payload={
                "available": True,
                "stage_counts": {
                    "signals_generated": 8,
                    "signals_approved": 5,
                    "risk_passed": 0,
                    "execution_attempted": 0,
                    "orders_routed": 0,
                },
            },
            inferred_signal_gate=None,
            inferred_execution_gate="execution_throttles",
        )
        self.assertEqual(blocker, "LIVE:risk:execution_throttles")

    def test_resolve_first_blocking_gate_prefers_readiness_failure(self):
        blocker = MetricCollector._resolve_first_blocking_gate(
            lifecycle_phase="WARM",
            runtime_state_payload={
                "available": True,
                "trading_state": "LIVE_PENDING_CONFIRMATION",
                "activation_committed": False,
            },
            readiness_proof_payload={
                "available": True,
                "first_blocking_gate": "nonce.ready",
            },
            decision_payload={
                "available": True,
                "allowed": False,
                "first_failed_gate": "nonce.authority",
                "decision": {"reason": "nonce.authority"},
            },
            validator_trace_payload={"available": False},
            pipeline_payload={
                "available": True,
                "stage_counts": {
                    "signals_generated": 0,
                    "signals_approved": 0,
                    "risk_passed": 0,
                    "execution_attempted": 0,
                    "orders_routed": 0,
                },
            },
            inferred_signal_gate=None,
            inferred_execution_gate=None,
        )
        self.assertEqual(blocker, "nonce.ready")

    def test_resolve_first_blocking_gate_reports_fsm_activation_completion(self):
        blocker = MetricCollector._resolve_first_blocking_gate(
            lifecycle_phase="WARM",
            runtime_state_payload={
                "available": True,
                "trading_state": "LIVE_PENDING_CONFIRMATION",
                "activation_committed": False,
            },
            readiness_proof_payload={
                "available": True,
                "first_blocking_gate": "none",
            },
            decision_payload={
                "available": True,
                "allowed": False,
                "first_failed_gate": "lifecycle.phase",
                "decision": {"reason": "lifecycle_phase:WARM"},
            },
            validator_trace_payload={"available": False},
            pipeline_payload={"available": False},
            inferred_signal_gate=None,
            inferred_execution_gate=None,
        )
        self.assertEqual(blocker, "fsm.activation_completion")


if __name__ == "__main__":
    unittest.main()
