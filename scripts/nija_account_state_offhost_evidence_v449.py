#!/usr/bin/env python3
"""Bounded, read-only account-JSON recovery evidence (v449).

Capture both per-account position and entry-price JSON directories before a
controlled trading redeploy. Run in the trusted Render owner shell, then
transfer the 0600 archive off-host over an approved encrypted channel.
A local archive, even with a matching hash, NEVER proves off-host custody,
ledger-to-JSON atomicity, Kraken provenance, protective orders or live trading.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import secrets
import stat
import tempfile
import zipfile
from pathlib import Path

MAX_FILES = 256
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_TOTAL_JSON_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 128 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
ACCOUNT_FILE = re.compile(r"(?:platform|user)__[A-Za-z0-9_.-]{1,90}\.json\Z")
KINDS = ("positions", "entry_prices")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _json_object(raw: bytes) -> dict:
    def reject_constant(value: str):
        raise ValueError("non-finite account JSON evidence")

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
        output: dict = {}
        for key, value in pairs:
            if key in output:
                raise ValueError("duplicate account JSON object key")
            output[key] = value
        return output

    try:
        value = json.loads(
            raw.decode("utf-8"), parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except ValueError as exc:
        # Keep the explicit ambiguity diagnostic; do not conceal a duplicate
        # object key as a generic parsing failure in an audit report.
        if str(exc) == "duplicate account JSON object key":
            raise
        raise ValueError("malformed account JSON evidence") from exc
    except (UnicodeError, TypeError) as exc:
        raise ValueError("malformed account JSON evidence") from exc
    if not isinstance(value, dict):
        raise ValueError("account JSON evidence must be an object")
    # json.loads can decode 1e999 to float('inf') without calling
    # parse_constant; recursively reject non-finite values from either path.
    pending = [value]
    checked = 0
    while pending:
        node = pending.pop()
        checked += 1
        if checked > 200000:
            raise ValueError("account JSON evidence structure too large")
        if isinstance(node, float) and not math.isfinite(node):
            raise ValueError("non-finite account JSON evidence")
        if isinstance(node, dict):
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    return value


def _read_unchanged(folder_fd: int, name: str) -> bytes:
    # A named pipe with a valid account filename must not block the backup
    # before fstat() can reject it. O_NONBLOCK is harmless on regular files.
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(name, flags, dir_fd=folder_fd)
    with os.fdopen(fd, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_JSON_BYTES:
            raise ValueError("unsafe or oversized account-state file")
        first = source.read(MAX_JSON_BYTES + 1)
        if len(first) != before.st_size:
            raise ValueError("account-state file changed while reading")
        source.seek(0)
        second = source.read(MAX_JSON_BYTES + 1)
        after = os.fstat(source.fileno())
        if (first != second or before.st_ino != after.st_ino
                or before.st_dev != after.st_dev
                or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns):
            raise ValueError("unstable account-state evidence")
    _json_object(first)
    return first


def _inventory(root: Path, directories: dict[str, Path]) -> dict[str, bytes]:
    payload: dict[str, bytes] = {}
    total_bytes = 0
    seen_directories: set[tuple[int, int]] = set()
    for kind in KINDS:
        requested = directories[kind]
        # Allow the documented /app/data *parent* symlink to the /data mount,
        # but never allow positions/ or entry_prices/ themselves to be aliases.
        if requested.is_symlink():
            raise ValueError("account-state source directory symlink rejected")
        directory = requested.resolve(strict=True)
        if not _inside(directory, root):
            raise ValueError("account-state directory outside persistent root")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        # Open the original requested leaf (not the resolved path) so that
        # O_NOFOLLOW still rejects a leaf swapped to a symlink.
        fd = os.open(requested, flags)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISDIR(metadata.st_mode):
                raise ValueError("unsafe account-state source directory")
            identity = (metadata.st_dev, metadata.st_ino)
            if identity in seen_directories:
                raise ValueError("account-state source directories share filesystem identity")
            seen_directories.add(identity)
            names = os.listdir(fd)
            if len(names) > MAX_FILES:
                raise ValueError("too many account-state files")
            for name in sorted(names):
                if not ACCOUNT_FILE.fullmatch(name):
                    raise ValueError("unexpected account-state filename")
                key = kind + "/" + name
                if key in payload or len(payload) >= MAX_FILES:
                    raise ValueError("duplicate or excess account-state file")
                raw = _read_unchanged(fd, name)
                total_bytes += len(raw)
                if total_bytes > MAX_TOTAL_JSON_BYTES:
                    raise ValueError("account-state evidence exceeds total byte budget")
                payload[key] = raw
        finally:
            os.close(fd)
    if not any(key.startswith("positions/") for key in payload):
        raise ValueError("position account-state directory is empty")
    return payload


def create_archive(*, persistent_root: Path, positions_dir: Path,
                   entry_prices_dir: Path, output_dir: Path) -> dict[str, object]:
    root = persistent_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("persistent root is not a directory")
    output = output_dir.resolve()
    if _inside(output, root) or output_dir.is_symlink():
        raise ValueError("output must not be in the live persistent mount")
    directories = {"positions": positions_dir, "entry_prices": entry_prices_dir}
    payload = _inventory(root, directories)
    # Two full passes catch a file changed while another account was copied.
    # This still does NOT make SQLite and JSON snapshots atomic.
    if _inventory(root, directories) != payload:
        raise ValueError("account-state changed across collection passes")
    manifest = {
        "format_version": 1,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "account_state_members": {
            key: {"bytes": len(raw), "sha256": _sha(raw)}
            for key, raw in sorted(payload.items())
        },
        "live_source_files_unmodified": True,
        "cross_store_atomicity_verified": False,
        "off_host_copy_verified": False,
        "isolated_restoration_verified": False,
        "broker_position_and_basis_verified": False,
        "trading_authorized": False,
    }
    manifest_raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(manifest_raw) > MAX_MANIFEST_BYTES:
        raise ValueError("account evidence manifest too large")
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output.is_symlink():
        raise ValueError("unsafe output directory")
    name = "nija-account-state-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name += "-" + secrets.token_hex(6) + ".zip"
    archive = output / name
    previous_umask = os.umask(0o077)
    try:
        # x mode refuses overwrites; no account files are modified.
        with zipfile.ZipFile(archive, mode="x", compression=zipfile.ZIP_DEFLATED) as saved:
            for key, raw in sorted(payload.items()):
                saved.writestr(key, raw)
            saved.writestr("manifest.json", manifest_raw)
        archive.chmod(0o600)
        with archive.open("rb") as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    finally:
        os.umask(previous_umask)
    return {
        "archive": str(archive), "sha256": digest.hexdigest(),
        "account_files": len(payload),
        "off_host_copy_verified": False, "cross_store_atomicity_verified": False,
        "trading_authorized": False,
        "next": "Transfer securely off host, then verify original SHA-256 on an isolated machine.",
    }


def verify_archive(path: Path, *, expected_sha256: str) -> dict[str, object]:
    if (len(expected_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in expected_sha256.lower())):
        raise ValueError("expected SHA-256 must be 64 hex characters")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("unsafe or oversized source archive")
    # Pin and hash exactly the same bytes that are subsequently inspected.
    with tempfile.TemporaryDirectory(prefix="nija-account-state-verify-") as temporary:
        pinned = Path(temporary) / "evidence.zip"
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as source, pinned.open("xb") as destination:
            original = os.fstat(source.fileno())
            if not stat.S_ISREG(original.st_mode) or original.st_size > MAX_ARCHIVE_BYTES:
                raise ValueError("unsafe source archive")
            digest = hashlib.sha256()
            copied = 0
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                copied += len(chunk)
                if copied > MAX_ARCHIVE_BYTES:
                    raise ValueError("archive size exceeded")
                digest.update(chunk)
                destination.write(chunk)
            if copied != original.st_size:
                raise ValueError("source archive changed while copying")
        if digest.hexdigest() != expected_sha256.lower():
            raise ValueError("archive checksum mismatch")
        with zipfile.ZipFile(pinned, "r") as saved:
            rows = saved.infolist()
            if len(rows) > MAX_FILES + 1:
                raise ValueError("too many archive members")
            names = [row.filename for row in rows]
            if len(names) != len(set(names)) or "manifest.json" not in names:
                raise ValueError("duplicate or missing manifest")
            limit = 0
            observed: dict[str, bytes] = {}
            for row in rows:
                name = row.filename
                if name != "manifest.json":
                    prefix, sep, basename = name.partition("/")
                    if prefix not in KINDS or sep != "/" or not ACCOUNT_FILE.fullmatch(basename):
                        raise ValueError("unsafe archive account member")
                maximum = MAX_MANIFEST_BYTES if name == "manifest.json" else MAX_JSON_BYTES
                if row.is_dir() or stat.S_ISLNK(row.external_attr >> 16):
                    raise ValueError("archive contains nonregular file")
                if row.file_size > maximum or row.compress_size > MAX_ARCHIVE_BYTES:
                    raise ValueError("oversized archive member")
                limit += row.file_size
                if limit > MAX_TOTAL_JSON_BYTES + MAX_MANIFEST_BYTES:
                    raise ValueError("decompressed archive size exceeded")
                with saved.open(row, "r") as source:
                    raw = source.read(maximum + 1)
                    if len(raw) != row.file_size or len(raw) > maximum:
                        raise ValueError("unexpected decompressed member size")
                observed[name] = raw
            # Validate manifest with the same duplicate-key and finite-number
            # rules as the per-account evidence, before trusting member claims.
            manifest = _json_object(observed.pop("manifest.json"))
            if type(manifest.get("format_version")) is not int or manifest["format_version"] != 1:
                raise ValueError("invalid archive manifest")
            records = manifest.get("account_state_members")
            if not isinstance(records, dict) or set(records) != set(observed):
                raise ValueError("archive inventory mismatch")
            if not any(k.startswith("positions/") for k in records):
                raise ValueError("account position evidence missing")
            for name, raw in observed.items():
                record = records[name]
                if (not isinstance(record, dict) or type(record.get("bytes")) is not int
                        or record["bytes"] != len(raw) or record.get("sha256") != _sha(raw)):
                    raise ValueError("account-state member checksum mismatch")
                _json_object(raw)
        return {
            "archive_sha256_matched": True, "account_files_verified": len(observed),
            "off_host_custody_independently_verified": False,
            "live_ledger_to_json_atomicity_verified": False,
            "historical_cost_basis_verified": False, "trading_authorized": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    backup = actions.add_parser("snapshot")
    backup.add_argument("--persistent-root", type=Path, default=Path("/data"))
    backup.add_argument("--positions-dir", type=Path, default=Path("/data/positions"))
    backup.add_argument("--entry-prices-dir", type=Path, default=Path("/data/entry_prices"))
    backup.add_argument("--output-dir", type=Path, required=True)
    audit = actions.add_parser("verify")
    audit.add_argument("--archive", type=Path, required=True)
    audit.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.action == "snapshot":
            result = create_archive(persistent_root=args.persistent_root,
                                    positions_dir=args.positions_dir,
                                    entry_prices_dir=args.entry_prices_dir,
                                    output_dir=args.output_dir)
        else:
            result = verify_archive(args.archive, expected_sha256=args.expected_sha256)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        print(json.dumps({
            "status": "FAILED_CLOSED", "error_type": type(exc).__name__,
            "off_host_custody_independently_verified": False,
            "trading_authorized": False,
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
