#!/usr/bin/env python3
"""Preserve NIJA's account-scoped JSON on the *existing* running instance.

This captures raw bytes from BOTH ephemeral directories without importing the
trading bot or modifying source files. It supplements the v436 SQLite online
backup; it does not repair missing historical fills, prove cross-file
atomicity, authorize trades, or prove off-host retention.

The bundle CONTAINS PRIVATE ACCOUNT DATA (base64 is not encryption). Keep it
mode 0600, transmit only via authenticated encrypted transport, and never
attach it to a public issue/CI artifact.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

FORMAT = "nija-account-state-preservation-v1"
SCOPES = ("positions", "entry_prices")
MAX_FILES = 512
MAX_SINGLE = 4 * 1024 * 1024
MAX_TOTAL = 16 * 1024 * 1024
MAX_BUNDLE = 24 * 1024 * 1024
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,230}\.json\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _metadata(st):
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _open_dir(path):
    """Resolve each path component with no symlink traversal, POSIX only."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    absolute = Path(os.path.abspath(path))
    fd = os.open("/", flags)
    try:
        for part in absolute.parts[1:]:
            new_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = new_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def _inventory(fd):
    names = sorted(os.listdir(fd))
    if len(names) > MAX_FILES:
        raise ValueError("too_many_files")
    records = {}
    for name in names:
        if not SAFE_NAME.fullmatch(name):
            raise ValueError("unexpected_member_name")
        st = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > MAX_SINGLE:
            raise ValueError("unsafe_or_oversized_member")
        records[name] = _metadata(st)
    return records


def _read_exact(fd, name, metadata):
    opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(opened, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError("nonregular_member")
        if _metadata(before) != metadata:
            raise ValueError("source_changed_before_read")
        content = stream.read(MAX_SINGLE + 1)
        if len(content) != before.st_size or _metadata(os.fstat(stream.fileno())) != metadata:
            raise ValueError("source_changed_while_reading")
    return content


def _write_private(path, raw):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_manifest_key")
        result[key] = value
    return result


def _pinned_bundle_bytes(path):
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BUNDLE:
            raise ValueError("invalid_bundle")
        raw = stream.read(MAX_BUNDLE + 1)
        after = os.fstat(stream.fileno())
        if len(raw) != before.st_size or _metadata(before) != _metadata(after):
            raise ValueError("bundle_changed_while_reading")
    return raw


def verify_bundle(path, expected_sha256, *, isolated_restore=False):
    expected = str(expected_sha256).lower()
    if not SHA256.fullmatch(expected):
        raise ValueError("invalid_source_sha256")
    raw = _pinned_bundle_bytes(Path(path))
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("source_digest_mismatch")
    obj = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    if (not isinstance(obj, dict) or obj.get("format") != FORMAT
            or obj.get("scopes") != list(SCOPES)
            or set(obj) != {"format", "scopes", "records", "created_at_utc",
                            "cross_store_atomicity_verified"}):
        raise ValueError("invalid_bundle_schema")
    if obj["cross_store_atomicity_verified"] is not False:
        raise ValueError("unverified_atomicity_claim")
    rows = obj["records"]
    if not isinstance(rows, list) or len(rows) > MAX_FILES:
        raise ValueError("invalid_record_count")
    files, totals, total_bytes = {}, {scope: 0 for scope in SCOPES}, 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"scope", "name", "bytes", "sha256", "b64"}:
            raise ValueError("invalid_member_schema")
        scope, name = row["scope"], row["name"]
        if type(scope) is not str or scope not in SCOPES or type(name) is not str or not SAFE_NAME.fullmatch(name):
            raise ValueError("invalid_member_path")
        if (scope, name) in files:
            raise ValueError("duplicate_member")
        if type(row["bytes"]) is not int or not (0 <= row["bytes"] <= MAX_SINGLE):
            raise ValueError("invalid_member_length")
        if not isinstance(row["sha256"], str) or not SHA256.fullmatch(row["sha256"]):
            raise ValueError("invalid_member_digest")
        encoded = row["b64"]
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_SINGLE + 2) // 3):
            raise ValueError("invalid_member_encoding")
        content = base64.b64decode(encoded, validate=True)
        if len(content) != row["bytes"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise ValueError("member_digest_mismatch")
        total_bytes += len(content)
        if total_bytes > MAX_TOTAL:
            raise ValueError("total_size_exceeded")
        files[(scope, name)] = content
        totals[scope] += 1
    if isolated_restore:
        with tempfile.TemporaryDirectory(prefix="nija-account-restore-check-") as temp:
            root = Path(temp)
            for scope in SCOPES:
                (root / scope).mkdir(mode=0o700)
            for (scope, name), content in files.items():
                path = root / scope / name
                _write_private(path, content)
                if path.read_bytes() != content:
                    raise ValueError("isolated_restore_mismatch")
    return {
        "source_digest_matched": True,
        "isolated_restore_verified": isolated_restore,
        "scope_counts": totals,
        "off_host_retention_verified": False,
        "cross_store_atomicity_verified": False,
        "brokerage_history_reconciled": False,
        "live_trading_authorized": False,
    }


def capture(positions, entry_prices, output_dir):
    source_paths = {"positions": os.path.abspath(positions),
                    "entry_prices": os.path.abspath(entry_prices)}
    destination = os.path.abspath(output_dir)
    if source_paths["positions"] == source_paths["entry_prices"]:
        raise ValueError("source_scopes_collide")
    for src in source_paths.values():
        if os.path.commonpath((src, destination)) == src:
            raise ValueError("output_inside_source")
    fds = {}
    try:
        for scope in SCOPES:
            fds[scope] = _open_dir(source_paths[scope])
        if len({(os.fstat(fd).st_dev, os.fstat(fd).st_ino) for fd in fds.values()}) != 2:
            raise ValueError("source_directory_alias")
        initial = {scope: _inventory(fds[scope]) for scope in SCOPES}
        records = []
        byte_count = 0
        for scope in SCOPES:
            for name, signature in initial[scope].items():
                content = _read_exact(fds[scope], name, signature)
                byte_count += len(content)
                if byte_count > MAX_TOTAL or len(records) == MAX_FILES:
                    raise ValueError("size_or_file_limit_exceeded")
                records.append({"scope": scope, "name": name, "bytes": len(content),
                                "sha256": hashlib.sha256(content).hexdigest(),
                                "b64": base64.b64encode(content).decode("ascii")})
        for scope in SCOPES:
            if _inventory(fds[scope]) != initial[scope]:
                raise ValueError("source_changed_during_capture")
            check = _open_dir(source_paths[scope])
            try:
                if (os.fstat(check).st_dev, os.fstat(check).st_ino) != (
                        os.fstat(fds[scope]).st_dev, os.fstat(fds[scope]).st_ino):
                    raise ValueError("source_directory_replaced")
            finally:
                os.close(check)
    finally:
        for fd in fds.values():
            os.close(fd)
    output_fd = _open_dir(destination)  # Must already exist; cannot be a symlink.
    os.close(output_fd)
    doc = {"format": FORMAT, "scopes": list(SCOPES), "records": records,
           "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
           "cross_store_atomicity_verified": False}
    raw = (json.dumps(doc, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    if len(raw) > MAX_BUNDLE:
        raise ValueError("encoded_bundle_too_large")
    stage = Path(tempfile.mkdtemp(prefix="nija-account-snapshot-", dir=destination))
    os.chmod(stage, 0o700)
    bundle = stage / "account-state-private.json"
    _write_private(bundle, raw)
    sha = hashlib.sha256(raw).hexdigest()
    result = verify_bundle(bundle, sha, isolated_restore=True)
    result.update({"archive": str(bundle), "sha256": sha, "bytes": len(raw),
                   "action_required": "Copy bundle and the v436 SQLite snapshot off Render "
                   "using encrypted transport. On the independent host, compare SHA-256 and "
                   "run restore-test. Verify historical entries separately before any release."})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--positions", required=True)
    backup.add_argument("--entry-prices", required=True)
    backup.add_argument("--output-dir", required=True)
    for name in ("verify", "restore-test"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--bundle", required=True)
        cmd.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.action == "backup":
            answer = capture(args.positions, args.entry_prices, args.output_dir)
        else:
            answer = verify_bundle(args.bundle, args.expected_sha256,
                                   isolated_restore=args.action == "restore-test")
        print(json.dumps(answer, sort_keys=True, indent=2))
        return 0
    except Exception as exc:
        # Never emit sensitive filenames, paths, raw records or account contents.
        print(json.dumps({"status": "FAILED_CLOSED", "error_type": type(exc).__name__,
                          "live_trading_authorized": False}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
