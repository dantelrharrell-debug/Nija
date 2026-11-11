"""Conservative offline pilot input gates; not a production DLP system."""
import re

BLOCKED = [
    r"\b(api[_ -]?key|secret[_ -]?key|private[_ -]?key|password|seed phrase|access token)\b",
    r"\b(buy|sell|place|execute|submit|open|close)\b.{0,50}\b(order|trade|position|btc|eth|stock)\b",
    r"\b(connect|authenticate|login)\b.{0,40}\b(broker|exchange|account)\b",
    r"\b(my|our)\b.{0,25}\b(balance|portfolio|account number|holdings|income)\b",
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
    r"\b(?:\d[ -]*?){13,19}\b",
    r"\b(ignore|override|disregard)\b.{0,60}\b(instructions|rules|safety|system prompt)\b",
    r"\b(reveal|print|show)\b.{0,40}\b(system prompt|developer message|hidden instructions)\b",
]
def validate_question(question):
    if not isinstance(question, str) or not 3 <= len(question.strip()) <= 300:
        raise ValueError("Question must be 3-300 characters")
    if any(re.search(pattern, question, re.I) for pattern in BLOCKED):
        raise ValueError("Sensitive or execution-related input is not allowed")
    return question.strip()
