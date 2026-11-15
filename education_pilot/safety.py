"""Conservative offline-only input gates; NOT production DLP."""
import re

BLOCKED = [
    r"\b(api[_ -]?key|secret[_ -]?key|private[_ -]?key|password|passphrase|seed[ _-]?phrase|recovery[ _-]?phrase|access[ _-]?token|bearer[ _-]?token)\b",
    r"\b(buy|sell|place|execute|submit|open|close)\b.{0,50}\b(order|trade|position|btc|eth|stock)\b",
    r"\b(connect|authenticate|login|log in|link)\b.{0,40}\b(broker|exchange|account)\b",
    r"\b(my|our)\b.{0,25}\b(balance|portfolio|account number|holdings|income)\b",
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
    r"\b(?:\d[ -]*?){13,19}\b",
    r"\b(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}\b",
    r"\b(?:\d{3}[ -]?\d{2}[ -]?\d{4})\b",
]
_PATTERNS = tuple(re.compile(pattern, re.I) for pattern in BLOCKED)


def validate_question(question):
    if not isinstance(question, str) or not 3 <= len(question.strip()) <= 300:
        raise ValueError("Question must be 3-300 characters")
    if any(pattern.search(question) for pattern in _PATTERNS):
        raise ValueError("Sensitive or execution-related input is not allowed")
    return question.strip()
