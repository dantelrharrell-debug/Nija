"""Standalone tutor, deliberately not mounted into Flask or production."""
from .budget import Budget
from .lesson_context import LESSONS
from .provider import MockProvider
from .safety import validate_question

class Tutor:
    def __init__(self, provider=None, budget=None):
        self.provider = provider if provider is not None else MockProvider()
        self.budget = budget if budget is not None else Budget()

    def explain(self, lesson_id, question):
        if lesson_id not in LESSONS:
            raise ValueError("Unknown or unapproved lesson")
        validated = validate_question(question)
        self.budget.consume()
        result = self.provider.explain(lesson_id, validated)
        required = ("explanation", "practice_question", "disclaimer", "provider")
        if not isinstance(result, dict) or any(not isinstance(result.get(k), str) or not result[k] for k in required):
            raise ValueError("Invalid provider response")
        if result["provider"] != "mock":
            raise ValueError("Non-mock providers prohibited in this pilot")
        return {"lesson_id": lesson_id, **result}
