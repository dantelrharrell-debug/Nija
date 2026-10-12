#!/usr/bin/env python3
"""Run the complete unittest suite with an exact known-failure ratchet."""
from __future__ import annotations

import argparse
import faulthandler
import importlib
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from urllib.parse import unquote


FailureKey = tuple[str, str]
_KINDS = {"FAIL", "ERROR"}
_TEST_ONLY_RESTART_THREAD_NAMES = frozenset({
    "entrypoint-writer-unhandled-loss-restart",
    "entrypoint-writer-unhandled-loss-restart-v300",
    "terminal-writer-loss-forced-restart",
    "writer-authority-forced-restart",
})
_TEST_RESTART_GRACE_ENV_NAMES = (
    "NIJA_WRITER_AUTHORITY_FALLBACK_RESTART_GRACE_S",
    "NIJA_WRITER_AUTHORITY_RESTART_GRACE_S",
    "NIJA_CORE_REGISTRATION_RESTART_GRACE_S",
)
_TEST_RESTART_GRACE_S = "3600"


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


def _normalize_named_import_failure_ids(
    observed: set[FailureKey],
    modules: list[str],
    baseline: set[FailureKey],
) -> set[FailureKey]:
    """Retain unittest discovery IDs for pre-existing import failures.

    \`unittest.discover\` reports _FailedTest.bot.test_foo, but
    \`loadTestsFromNames(['bot.test_foo'])\` can report
    _FailedTest.test_foo. Map ONLY an unambiguous matching module
    already present in the checked-in failure baseline, and preserve all
    other unexpected import errors as failures.
    """
    prefix = "unittest.loader._FailedTest."
    normalized: set[FailureKey] = set()
    for kind, test_id in observed:
        if not test_id.startswith(prefix) or (kind, test_id) in baseline:
            normalized.add((kind, test_id))
            continue
        short = test_id[len(prefix):]
        candidates = [
            module for module in modules
            if (module == short or module.endswith("." + short))
            and (kind, prefix + module) in baseline
        ]
        if len(candidates) == 1:
            normalized.add((kind, prefix + candidates[0]))
        else:
            normalized.add((kind, test_id))
    return normalized


def _load_named_modules_like_discovery(
    names: list[str], start_dir: str = "."
) -> unittest.TestSuite:
    """Load explicit modules with unittest.discover's import failure behavior.

    Unlike loadTestsFromNames, discovery catches *all* module-level import
    failures, including pytest.skip.Exception (a BaseException). Preserve the
    full import ID when constructing _FailedTest, so the exact checked-in
    baseline continues to apply. Missing/import-failing tests are NOT skipped.
    """
    loader = unittest.defaultTestLoader
    groups: list[unittest.TestSuite] = []
    root = Path(start_dir).resolve()
    for name in names:
        try:
            module = importlib.import_module(name)
            expected = root.joinpath(*name.split(".")).with_suffix(".py").resolve()
            actual = Path(getattr(module, "__file__", "")).resolve()
            if actual != expected:
                raise ImportError(f"CI_MODULE_PATH_MISMATCH: {name}")
        except unittest.SkipTest as exc:
            skipped_case = unittest.loader._make_skipped_test(name, exc, loader.suiteClass)
            groups.append(skipped_case)
        except BaseException:
            failed_case, message = unittest.loader._make_failed_import_test(
                name, loader.suiteClass
            )
            loader.errors.append(message)
            groups.append(failed_case)
        else:
            groups.append(loader.loadTestsFromModule(module))
    return loader.suiteClass(groups)


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
    parser.add_argument("--traceback-after", type=int, help="Repeat diagnostic thread stacks after this many seconds")
    parser.add_argument("--preload-module", action="append", default=[],
                        help="Import a dependency before discovery can start runtime monitor threads")
    parser.add_argument("--report-json", type=Path,
                        help="Write complete, machine-readable test results for an isolated CI partition")
    parser.add_argument("--module", action="append", default=[],
                        help="Run named unittest module(s) instead of importing the entire suite")
    args = parser.parse_args(argv)
    if args.traceback_after is not None and args.traceback_after <= 0:
        parser.error("--traceback-after must be positive")

    try:
        baseline = _parse_baseline(args.baseline)
    except (OSError, ValueError) as exc:
        print(f"CI_BASELINE_INVALID: {exc}", file=sys.stderr)
        return 2

    # A few writer-authority tests intentionally arm production os._exit(75)
    # fallbacks. Keep those callbacks far outside the test duration and cancel
    # their explicitly named timers between cases. Production defaults and
    # behavior are untouched because this environment exists only in CI.
    saved_restart_grace = {
        env_name: os.environ.get(env_name)
        for env_name in _TEST_RESTART_GRACE_ENV_NAMES
    }
    try:
        if args.traceback_after is not None:
            faulthandler.dump_traceback_later(args.traceback_after, repeat=True)
        for env_name in _TEST_RESTART_GRACE_ENV_NAMES:
            os.environ[env_name] = _TEST_RESTART_GRACE_S

        _reset_terminal_writer_loss_test_state()
        # requests lazily imports urllib3. Discovery can start runtime monitors
        # that import the same dependency concurrently through NIJA's import
        # hooks. Import the requested dependencies first, on this main thread.
        # A preload error remains a failed run; no test or failure is skipped.
        for module_name in args.preload_module:
            try:
                importlib.import_module(module_name)
            except Exception as exc:
                print(f"CI_PRELOAD_FAILED module={module_name} error={type(exc).__name__}: {exc}",
                      file=sys.stderr)
                return 2
        if args.module:
            # Explicit module names let CI isolate imports to a bounded group
            # without relying on filename globs or invoking unrelated hooks.
            suite = _load_named_modules_like_discovery(args.module, args.start_dir)
        else:
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
    finally:
        if args.traceback_after is not None:
            faulthandler.cancel_dump_traceback_later()
        for env_name, previous in saved_restart_grace.items():
            if previous is None:
                os.environ.pop(env_name, None)
            else:
                os.environ[env_name] = previous

    observed = _observed_failures(result)
    if args.module:
        observed = _normalize_named_import_failure_ids(observed, args.module, baseline)
    # Partitioned CI collects every test result and enforces the original
    # full-suite known-failure ratchet after all isolated child runs finish.
    # Keep ordinary single-process CLI behavior entirely unchanged.
    if args.report_json is not None:
        payload = {
            "schema": 1,
            "pattern": args.pattern,
            "modules": args.module,
            "tests_run": result.testsRun,
            "observed": [list(item) for item in sorted(observed)],
            "unexpected_successes": [test.id() for test in result.unexpectedSuccesses],
        }
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
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
