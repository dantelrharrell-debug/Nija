#!/usr/bin/env python3
"""Run the complete unittest suite with an exact known-failure ratchet."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import threading
import unittest
from urllib.parse import unquote


FailureKey = tuple[str, str]
_KINDS = {"FAIL", "ERROR"}
_TEST_ONLY_RESTART_THREAD_NAMES = frozenset({
    "terminal-writer-loss-forced-restart",
})


def _parse_baseline(path: Path) -> set[FailureKey]:
    entries: set[FailureKey] = set()
    test_ids: set[str] = set()
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            kind, test_id = line.split(maxsplit=1)
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: expected '<FAIL|ERROR> <test-id>'") from exc
        if kind not in _KINDS or not test_id.strip():
            raise ValueError(f"{path}:{line_number}: invalid baseline entry: {line!r}")
        entry = (kind, unquote(test_id.strip()))
        if entry in entries:
            raise ValueError(f"{path}:{line_number}: duplicate baseline entry: {line!r}")
        if entry[1] in test_ids:
            raise ValueError(
                f"{path}:{line_number}: test id has multiple baseline categories: "
                f"{entry[1]!r}"
            )
        entries.add(entry)
        test_ids.add(entry[1])
    return entries


def _reset_terminal_writer_loss_test_state() -> None:
    """Prevent one unit test's terminal-loss proof from killing later tests.

    Production correctly arms an ``os._exit(75)`` timer after terminal writer
    loss. Unit tests intentionally exercise that path, but the daemon Timer can
    outlive the test method and terminate the entire shared unittest process
    several tests later. Cancel only the explicitly named forced-restart timer
    and invoke the latch module's documented test-only reset hook between test
    cases. Production code and restart behavior are unchanged.
    """
    for thread in tuple(threading.enumerate()):
        if thread.name not in _TEST_ONLY_RESTART_THREAD_NAMES:
            continue
        cancel = getattr(thread, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                pass

    seen: set[int] = set()
    for module_name in (
        "bot.terminal_writer_loss_latch",
        "terminal_writer_loss_latch",
    ):
        module = sys.modules.get(module_name)
        if module is None or id(module) in seen:
            continue
        seen.add(id(module))
        reset = getattr(module, "reset_for_test", None)
        if callable(reset):
            try:
                reset()
            except Exception:
                pass


class _IsolatedTextTestResult(unittest.TextTestResult):
    """Text result that clears process-level restart state after every test."""

    def stopTest(self, test: unittest.case.TestCase) -> None:  # noqa: N802
        try:
            super().stopTest(test)
        finally:
            _reset_terminal_writer_loss_test_state()


def _observed_failures(result: unittest.TestResult) -> set[FailureKey]:
    failures = {("FAIL", test.id()) for test, _traceback in result.failures}
    errors = {("ERROR", test.id()) for test, _traceback in result.errors}
    return failures | errors


def _print_entries(title: str, entries: set[FailureKey]) -> None:
    if not entries:
        return
    print(f"\n{title} ({len(entries)}):")
    for kind, test_id in sorted(entries):
        print(f"  {kind} {test_id}")


def main(argv: list[str] | None = None) -> int:
    """Run discovery and reject every result outside the checked-in baseline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--start-dir", default=".")
    parser.add_argument("--pattern", default="test_*.py")
    args = parser.parse_args(argv)

    try:
        baseline = _parse_baseline(args.baseline)
    except (OSError, ValueError) as exc:
        print(f"CI_BASELINE_INVALID: {exc}", file=sys.stderr)
        return 2

    _reset_terminal_writer_loss_test_state()
    suite = unittest.defaultTestLoader.discover(
        start_dir=args.start_dir,
        pattern=args.pattern,
    )
    runner = unittest.TextTestRunner(
        verbosity=2,
        resultclass=_IsolatedTextTestResult,
    )
    result = runner.run(suite)
    _reset_terminal_writer_loss_test_state()

    observed = _observed_failures(result)
    unexpected = observed - baseline
    resolved = baseline - observed

    _print_entries("KNOWN_FAILURES_STILL_PRESENT", observed & baseline)
    _print_entries("KNOWN_FAILURES_RESOLVED", resolved)
    _print_entries("UNEXPECTED_TEST_RESULTS", unexpected)

    unexpected_successes = [test.id() for test in result.unexpectedSuccesses]
    if unexpected_successes:
        print(f"\nUNEXPECTED_SUCCESSES ({len(unexpected_successes)}):")
        for test_id in sorted(unexpected_successes):
            print(f"  {test_id}")

    if unexpected or unexpected_successes:
        print(
            "CI_BASELINE_RATCHET_FAILED "
            f"tests={result.testsRun} known={len(observed & baseline)} "
            f"resolved={len(resolved)} unexpected={len(unexpected)}"
        )
        return 1

    print(
        "CI_BASELINE_RATCHET_PASSED "
        f"tests={result.testsRun} known={len(observed & baseline)} "
        f"resolved={len(resolved)} unexpected=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
