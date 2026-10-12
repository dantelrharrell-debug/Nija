#!/usr/bin/env python3
"""Run the complete NIJA unittest baseline in short-lived isolated subprocesses.

The historical runner imports 700+ test modules into one interpreter before
running tests. Their import-time runtime monitors can retain mocked objects and
interfere with each other, intermittently crashing CI with SIGSEGV.

This orchestrator loads all discoverable modules in bounded worker processes,
without skipping modules or weakening the original known-failure ratchet.
No production hooks, safety controls, or trading authority are modified.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any

from run_unittest_baseline import _parse_baseline, _print_entries


FailureKey = tuple[str, str]


def _discoverable_modules(root: Path) -> list[str]:
    """Use Python 3.11 unittest's package-aware discovery inventory."""
    modules: list[str] = []
    for path in sorted(root.rglob("test_*.py")):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or ".git" in relative.parts:
            continue
        dirs = relative.parts[:-1]
        if not all(
            (root.joinpath(*dirs[:idx], "__init__.py")).is_file()
            for idx in range(1, len(dirs) + 1)
        ):
            continue
        module_parts = relative.with_suffix("").parts
        if any(not part.isidentifier() for part in module_parts):
            raise RuntimeError(f"CI_DISCOVERY_INVALID_MODULE path={relative.as_posix()}")
        modules.append(".".join(module_parts))
    if not modules or len(modules) != len(set(modules)):
        raise RuntimeError("CI_DISCOVERY_EMPTY_OR_DUPLICATE_MODULES")
    return modules


def _partitions(modules: list[str], max_files: int) -> list[list[str]]:
    """Deterministic disjoint chunks; every module must run exactly once."""
    groups = [
        modules[start : start + max_files]
        for start in range(0, len(modules), max_files)
    ]
    flattened = [name for group in groups for name in group]
    if flattened != modules or any(not group or len(group) > max_files for group in groups):
        raise RuntimeError("CI_PARTITION_MANIFEST_INVALID")
    return groups


def _log_tail(path: Path, limit: int = 100) -> str:
    try:
        return "\n".join(
            path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
        )
    except OSError:
        return "[CI log unavailable]"


def _load_report(path: Path, module_names: list[str]) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or data.get("modules") != module_names:
        raise RuntimeError("CI_PARTITION_REPORT_INVALID module inventory")
    if not isinstance(data.get("tests_run"), int) or data["tests_run"] < 0:
        raise RuntimeError("CI_PARTITION_REPORT_INVALID test count")
    if not isinstance(data.get("observed"), list):
        raise RuntimeError("CI_PARTITION_REPORT_INVALID observed failures")
    if not isinstance(data.get("unexpected_successes"), list):
        raise RuntimeError("CI_PARTITION_REPORT_INVALID unexpected successes")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--preload-module", action="append", default=[])
    parser.add_argument("--traceback-after", type=int, default=120)
    parser.add_argument("--max-files", type=int, default=25)
    parser.add_argument("--max-partition-seconds", type=int, default=540)
    parser.add_argument("--min-tests", type=int, default=2554,
                        help="Minimum cases from the last verified 2,554-test suite")
    parser.add_argument("--list-only", action="store_true")
    args = parser.parse_args(argv)
    if args.max_files < 1 or args.max_files > 100:
        parser.error("--max-files must be 1..100")
    if args.max_partition_seconds < 30 or args.traceback_after <= 0:
        parser.error("timeout and traceback intervals must be positive")

    root = Path(__file__).resolve().parents[1]
    baseline_path = args.baseline if args.baseline.is_absolute() else root / args.baseline
    try:
        baseline = _parse_baseline(baseline_path)
        modules = _discoverable_modules(root)
        groups = _partitions(modules, args.max_files)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"CI_PARTITION_SETUP_FAILED: {exc}", file=sys.stderr, flush=True)
        return 2

    print(
        f"CI_PARTITION_MANIFEST modules={len(modules)} groups={len(groups)} "
        f"max_files={args.max_files} min_tests={args.min_tests}",
        flush=True,
    )
    if args.list_only:
        for index, group in enumerate(groups, 1):
            print(f"  partition={index} modules={len(group)} first={group[0]} last={group[-1]}")
        return 0

    total_tests = 0
    observed: set[FailureKey] = set()
    unexpected_successes: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="nija-ci-unittest-") as work:
        workdir = Path(work)
        for index, module_names in enumerate(groups, 1):
            report_file = workdir / f"part-{index:03d}.json"
            log_file = workdir / f"part-{index:03d}.log"
            command = [
                # -m keeps the repository root on sys.path. Running the
                # script by absolute path makes only scripts/ importable and
                # turns every bot.* test into a false _FailedTest.bot error.
                sys.executable, "-u", "-m", "scripts.run_unittest_baseline",
                "--baseline", str(baseline_path),
                "--report-json", str(report_file),
                "--traceback-after", str(args.traceback_after),
            ]
            for module_name in module_names:
                command += ["--module", module_name]
            for module_name in args.preload_module:
                command += ["--preload-module", module_name]
            print(
                f"CI_PARTITION_START index={index}/{len(groups)} "
                f"modules={len(module_names)}",
                flush=True,
            )
            started = time.monotonic()
            with log_file.open("w", encoding="utf-8") as output:
                try:
                    completed = subprocess.run(
                        command,
                        cwd=root,
                        env=os.environ.copy(),
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        timeout=args.max_partition_seconds,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    print(
                        f"CI_PARTITION_TIMEOUT index={index} "
                        f"timeout_s={args.max_partition_seconds}\n{_log_tail(log_file)}",
                        file=sys.stderr,
                        flush=True,
                    )
                    return 2
            duration = round(time.monotonic() - started, 2)
            if completed.returncode != 0:
                print(
                    f"CI_PARTITION_FAILED index={index} returncode={completed.returncode} "
                    f"elapsed_s={duration}\n{_log_tail(log_file)}",
                    file=sys.stderr,
                    flush=True,
                )
                return 2

            try:
                data = _load_report(report_file, module_names)
                for item in data["observed"]:
                    if (
                        not isinstance(item, list)
                        or len(item) != 2
                        or item[0] not in {"FAIL", "ERROR"}
                        or not all(isinstance(part, str) for part in item)
                    ):
                        raise RuntimeError("CI_PARTITION_REPORT_INVALID failure entry")
                    observed.add((item[0], item[1]))
                successes = data["unexpected_successes"]
                if not all(isinstance(test_id, str) for test_id in successes):
                    raise RuntimeError("CI_PARTITION_REPORT_INVALID unexpected successes")
                unexpected_successes.update(successes)
            except (OSError, ValueError, KeyError, RuntimeError) as exc:
                print(
                    f"CI_PARTITION_REPORT_FAILED index={index} error={exc}",
                    file=sys.stderr,
                    flush=True,
                )
                return 2
            total_tests += data["tests_run"]
            print(
                f"CI_PARTITION_COMPLETE index={index}/{len(groups)} "
                f"tests={data['tests_run']} elapsed_s={duration} "
                f"cumulative_tests={total_tests}",
                flush=True,
            )

    unexpected = observed - baseline
    resolved = baseline - observed
    if total_tests < args.min_tests:
        print(
            f"CI_PARTITION_COVERAGE_FAILED tests={total_tests} min={args.min_tests}",
            file=sys.stderr,
            flush=True,
        )
        return 2
    _print_entries("KNOWN_FAILURES_STILL_PRESENT", observed & baseline)
    _print_entries("KNOWN_FAILURES_RESOLVED", resolved)
    _print_entries("UNEXPECTED_TEST_RESULTS", unexpected)
    if unexpected_successes:
        print(
            f"UNEXPECTED_SUCCESSES count={len(unexpected_successes)} "
            f"ids={sorted(unexpected_successes)!r}",
            flush=True,
        )
    if unexpected or unexpected_successes:
        print(
            f"CI_BASELINE_RATCHET_FAILED tests={total_tests} "
            f"known={len(observed & baseline)} resolved={len(resolved)} "
            f"unexpected={len(unexpected)} unexpected_successes={len(unexpected_successes)}",
            flush=True,
        )
        return 1
    print(
        f"CI_BASELINE_RATCHET_PASSED tests={total_tests} "
        f"known={len(observed & baseline)} resolved={len(resolved)} unexpected=0 "
        f"isolated_processes={len(groups)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
