"""Deterministic mock provider. No network, SDK, credentials or billable calls."""
class MockProvider:
    def explain(self, lesson_id, question):
        if lesson_id == "lesson_003":
            explanation = ("Risk per trade is a planned maximum loss, not the amount invested. "
                           "A hypothetical $1,000 account risking 1% plans for a $10 loss. "
                           "Actual losses may exceed plans due to slippage or gaps.")
            check = "What is 1% of a fictional $2,000 account?"
        elif lesson_id == "lesson_002":
            explanation = ("RSI is a momentum indicator. Common 70/30 thresholds describe "
                           "conditions, not reliable buy or sell instructions.")
            check = "Why does an RSI above 70 not guarantee a reversal?"
        elif lesson_id == "lesson_005":
            explanation = ("A written practice plan and journal can help identify emotional "
                           "biases; neither removes market uncertainty.")
            check = "Name one bias that may affect a hypothetical decision."
        else:
            explanation = ("Markets match buyers and sellers; order types differ in execution "
                           "and price certainty. This is a conceptual explanation only.")
            check = "How does a market order differ from a limit order?"
        return {"explanation": explanation, "practice_question": check,
                "disclaimer": "Education only; not personalized investment advice.",
                "provider": "mock"}
