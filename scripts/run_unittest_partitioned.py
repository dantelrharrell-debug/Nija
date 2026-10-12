#!/usr/bin/env python3
"""Run the complete NIJA unittest baseline in short-lived isolated subprocesses.

The historical full-suite runner imports all 700+ discoverable test modules
before running cases. Many NIJA modules start daemon trading-monitor threads
on import; those long-lived threads retain mocks from unrelated tests and
have intermittently crashed the shared Python process with SIGSEGV.

This runner partitions by test filename, preserves normal unittest discovery
within each partition, and aggregates the EXACT original failure baseline.
It never skips a known failure, downgrades a crash, or grants trade authority.
Only CI test orchestration changes; production behavior stays unchanged.
"""
from __future__ import annotations

import argparse
import fnmatch
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


def _discoverable_files(root: Path) -> list[Path]:
    """Match Python 3.11's package-aware unittest discovery from repository root."""
    all_files = sorted(root.rglob("test_*.py"))
    matches: list[Path] = []
    for path in all_files:
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or ".git" in relative.parts:
            continue
        directories = relative.parts[:-1]
        if all((root.joinpath(*directories[:i], "__init__.py")).is_file()
               for i in range(1, len(directories) + 1)):
            matches.append(relative)
    return matches


def _partitions(files: list[Path], max_files: int) -> list[tuple[str, list[Path]]]:
    """Partition all candidate filenames into nonoverlapping unittest globs."""
    if not files:
        raise ValueError("No discoverable test files found")
    suffixes = {p: p.name[len("test_"):-len(".py")] for p in files}
    groups: list[tuple[str, list[Path]]] = []

    def split(prefix: str, members: list[Path]) -> None:
        if len(members) <= max_files:
            groups.append(("test_" + prefix + "*.py", members))
            return
        exact = [p for p in members if suffixes[p] == prefix]
        if exact:
            groups.append(("test_" + prefix + ".py", exact))
        children: dict[str, list[Path]] = {}
        for path in members:
            name = suffixes[path]
            if len(name) == len(prefix):
                continue
            nxt = name[len(prefix)]
            children.setdefault(nxt, []).append(path)
        for nxt, subset in sorted(children.items()):
            split(prefix + nxt, subset)

    split("", files)
    groups.sort(key=lambda x: x[0])
    # A glob mistake could silently omit tests. Fail before starting any run.
    for file in files:
        selected = [pat for pat, _ in groups if fnmatch.fnmatchcase(file.name, pat)]
        if len(selected) != 1:
            raise RuntimeError(
                f"CI_PARTITION_COVERAGE_INVALID file={file.as_posix()} matches={len(selected)}"
            )
    if sum(len(members) for _, members in groups) != len(files):
        raise RuntimeError("CI_PARTITION_COVERAGE_INVALID duplicate file in partition list")
    return groups


def _log_tail(path: Path, limit: int = 90) -> str:
    try:
        # Logs are bounded by per-partition test groups; read only on failure.
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "[CI log unavailable]"
    return "\n".join(lines[-limit:])


def _load_report(path: Path, pattern: str) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or data.get("pattern") != pattern:
        raise RuntimeError("CI_PARTITION_REPORT_INVALID schema or pattern")
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
                        help="Minimum cases from the last verified 2,554-test full-suite run")
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
        files = _discoverable_files(root)
        groups = _partitions(files, args.max_files)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"CI_PARTITION_SETUP_FAILED: {exc}", file=sys.stderr, flush=True)
        return 2

    print(
        f"CI_PARTITION_MANIFEST files={len(files)} groups={len(groups)} "
        f"max_files={args.max_files} min_tests={args.min_tests}",
        flush=True,
    )
    if args.list_only:
        for pattern, members in groups:
            print(f"  {pattern}: {len(members)} files")
        return 0

    total_tests = 0
    observed: set[FailureKey] = set()
    unexpected_successes: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="nija-ci-unittest-") as work:
        workdir = Path(work)
        for index, (pattern, members) in enumerate(groups, 1):
            report_file = workdir / f"part-{index:03d}.json"
            log_file = workdir / f"part-{index:03d}.log"
            command = [
                sys.executable, "-u", str(root / "scripts/run_unittest_baseline.py"),
                "--baseline", str(baseline_path),
                "--start-dir", ".",
                "--pattern", pattern,
                "--report-json", str(report_file),
                "--traceback-after", str(args.traceback_after),
            ]
            for module in args.preload_module:
                command += ["--preload-module", module]
            print(
                f"CI_PARTITION_START index={index}/{len(groups)} "
                f"pattern={pattern} files={len(members)}",
                flush=True,
            )
            started = time.monotonic()
            with log_file.open("w", encoding="utf-8") as output:
                try:
                    completed = subprocess.run(
                        command, cwd=root, env=os.environ.copy(),
                        stdout=output, stderr=subprocess.STDOUT,
                        timeout=args.max_partition_seconds, check=False,
                    )
                except subprocess.TimeoutExpired:
                    print(
                        f"CI_PARTITION_TIMEOUT pattern={pattern} "
                        f"timeout_s={args.max_partition_seconds}\n{_log_tail(log_file)}",
                        file=sys.stderr, flush=True,
                    )
                    return 2
            duration = round(time.monotonic() - started, 2)
            if completed.returncode != 0:
                print(
                    f"CI_PARTITION_FAILED pattern={pattern} returncode={completed.returncode} "
                    f"elapsed_s={duration}\n{_log_tail(log_file)}",
                    file=sys.stderr, flush=True,
                )
                return 2

            try:
                data = _load_report(report_file, pattern)
                for item in data["observed"]:
                    if (not isinstance(item, list) or len(item) != 2
                            or not all(isinstance(part, str) for part in item)
                            or item[0] not in {"FAIL", "ERROR"}):
                        raise RuntimeError("CI_PARTITION_REPORT_INVALID failure entry")
                    observed.add((item[0], item[1]))
                unexpected_successes.update(data["unexpected_successes"])
            except (OSError, ValueError, KeyError, RuntimeError) as exc:
                print(
                    f"CI_PARTITION_REPORT_FAILED pattern={pattern} error={exc}",
                    file=sys.stderr, flush=True,
                )
                return 2
            total_tests += data["tests_run"]
            print(
                f"CI_PARTITION_COMPLETE pattern={pattern} tests={data['tests_run']} "
                f"elapsed_s={duration} cumulative_tests={total_tests}",
                flush=True,
            )

    unexpected = observed - baseline
    resolved = baseline - observed
    if total_tests < args.min_tests:
        print(
            f"CI_PARTITION_COVERAGE_FAILED tests={total_tests} min={args.min_tests}",
            file=sys.stderr, flush=True,
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
