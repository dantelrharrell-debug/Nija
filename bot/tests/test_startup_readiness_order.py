import unittest
from pathlib import Path


class TestStartupReadinessOrder(unittest.TestCase):
    def test_bootstrap_ready_is_marked_before_prethread_barrier(self):
        bot_path = Path(__file__).resolve().parents[2] / "bot.py"
        source = bot_path.read_text(encoding="utf-8")

        bootstrap_ready_index = source.index('_rt_mark_ready("bootstrap_ready")')
        prethread_barrier_index = source.index("if not _rt_is_ready():")

        self.assertLess(bootstrap_ready_index, prethread_barrier_index)


if __name__ == "__main__":
    unittest.main()
