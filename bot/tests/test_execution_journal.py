import json
import os
import tempfile
import unittest

from bot.execution_journal import ExecutionJournal


class TestExecutionJournal(unittest.TestCase):
    def test_append_writes_jsonl_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal_path = os.path.join(tmp, "journal.jsonl")
            journal = ExecutionJournal(path=journal_path)

            first = journal.append(
                event_type="intent_created",
                intent_id="intent-1",
                payload={"symbol": "BTC-USD"},
                ts="2026-01-01T00:00:00+00:00",
            )
            second = journal.append(
                event_type="order_submitted",
                intent_id="intent-1",
                payload={"size_usd": 50.0},
                ts="2026-01-01T00:00:01+00:00",
            )

            self.assertEqual(first["event_type"], "intent_created")
            self.assertEqual(second["event_type"], "order_submitted")

            with open(journal_path, "r", encoding="utf-8") as fh:
                lines = [json.loads(line) for line in fh if line.strip()]
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0]["event_type"], "intent_created")
            self.assertEqual(lines[1]["event_type"], "order_submitted")

    def test_append_falls_back_to_in_memory_when_file_sink_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Directory path causes append(open(..., "a")) to fail and trigger fallback.
            journal = ExecutionJournal(path=tmp)
            record = journal.append(
                event_type="final_state",
                intent_id="intent-2",
                payload={"success": False},
            )

            self.assertEqual(record["event_type"], "final_state")
            self.assertEqual(len(journal._in_memory_events), 1)
            self.assertEqual(journal._in_memory_events[0]["intent_id"], "intent-2")

    def test_append_rejects_unknown_event_type(self):
        journal = ExecutionJournal(path="")
        with self.assertRaises(ValueError):
            journal.append(event_type="unknown_event", intent_id="intent-3", payload={})


if __name__ == "__main__":
    unittest.main()

