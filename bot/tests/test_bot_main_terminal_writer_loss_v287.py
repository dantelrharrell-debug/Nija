from __future__ import annotations

import types
import unittest
from unittest.mock import MagicMock, patch


class BotMainTerminalWriterLossV287Tests(unittest.TestCase):
    """Regression coverage for canonical terminal writer-loss delegation."""

    def test_on_lease_lost_delegates_to_terminal_latch(self):
        import bot.bot_main as bot_main
        import bot.entrypoint_writer_authority as authority

        previous_runtime = bot_main._writer_authority_runtime
        previous_monitor = bot_main._authority_heartbeat_monitor
        previous_exit_code = bot_main._process_exit_code
        previous_exit_reason = bot_main._process_exit_reason

        runtime = MagicMock()
        runtime.acquire_with_standby.return_value = types.SimpleNamespace(
            acquired=True,
            error="",
            holder="",
            pttl_ms=60000,
            token="writer-token-91",
            generation=91,
            instance_id="instance-91",
            local_fallback=False,
        )
        runtime._generation = 91
        monitor = MagicMock()

        try:
            bot_main._process_exit_code = 0
            bot_main._process_exit_reason = ""
            bot_main._shutdown_event.clear()

            with (
                patch.object(
                    authority,
                    "get_entrypoint_writer_authority",
                    return_value=runtime,
                ),
                patch.object(
                    authority,
                    "bind_entrypoint_writer_authority_aliases",
                    return_value=runtime,
                ),
                patch(
                    "bot.authority_heartbeat.start_authority_heartbeat",
                    return_value=monitor,
                ),
                patch(
                    "bot.execution_authority_context.assert_distributed_writer_authority"
                ),
                patch(
                    "bot.terminal_writer_loss_latch.report_terminal_writer_loss",
                    return_value=True,
                ) as report_loss,
            ):
                self.assertTrue(bot_main._acquire_writer_authority_before_nonce())
                runtime.set_on_lost_callback.assert_called_once()
                callback = runtime.set_on_lost_callback.call_args.args[0]
                handled = callback("core_thread_registration_deadline_exceeded")

            self.assertTrue(handled)
            monitor.stop.assert_called_once_with()
            report_loss.assert_called_once_with(
                "core_thread_registration_deadline_exceeded",
                source="on_lease_lost",
            )
        finally:
            bot_main._writer_authority_runtime = previous_runtime
            bot_main._authority_heartbeat_monitor = previous_monitor
            bot_main._process_exit_code = previous_exit_code
            bot_main._process_exit_reason = previous_exit_reason
            bot_main._shutdown_event.clear()


if __name__ == "__main__":
    unittest.main()
