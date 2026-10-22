#!/usr/bin/env python3
"""Private, non-authorizing preservation of NIJA legacy global account files.

This utility is deliberately separate from the account-scoped v449 and online
SQLite v436 archives. It copies *existing* explicitly enumerated legacy files
without converting them into current account positions, inferred cost basis,
or trading proof. Use only from the existing authorized live Render owner shell.

An operator must separately prove encrypted off-host custody and independently
restore/inspect the full current recovery set. This tool never grants trading.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import zipfile

MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 12 * 1024 * 1024
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_BYTES = 32 * 1024
LABEL = re.compile(r"[a-z][a-z0-9_-]{0,47}\Z")
DEFAULT_SOURCES = {
    "data-positions": Path("/app/data/positions.json"),
    "data-entry-prices": Path("/app/data/entry_prices.json"),
    "app-positions": Path("/app/positions.json"),
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _identity(s: os.stat_result) -> tuple[int, int, int, int, int]:
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def _unique_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("duplicate archive manifest key")
        output[key] = value
    return output


def _read_stable_file(source: Path) -> tuple[bytes, os.stat_result] | None:
    """Read the same regular-file inode twice; never follow a leaf symlink."""
    try:
        before_path = source.lstat()
    except FileNotFoundError:
        return None
    if (not stat.S_ISREG(before_path.st_mode)
            or before_path.st_size > MAX_FILE_BYTES
            or before_path.st_nlink != 1):
        raise ValueError("unsafe legacy source type")
    fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as reader:
        before_fd = os.fstat(reader.fileno())
        if (not stat.S_ISREG(before_fd.st_mode)
                or _identity(before_fd) != _identity(before_path)):
            raise ValueError("legacy source changed before read")
        first = reader.read(MAX_FILE_BYTES + 1)
        reader.seek(0)
        second = reader.read(MAX_FILE_BYTES + 1)
        after_fd = os.fstat(reader.fileno())
    try:
        after_path = source.lstat()
    except FileNotFoundError as exc:
        raise ValueError("legacy source vanished during capture") from exc
    if (first != second or len(first) > MAX_FILE_BYTES
            or len(first) != before_fd.st_size
            or _identity(before_fd) != _identity(after_fd)
            or _identity(after_fd) != _identity(after_path)):
        raise ValueError("unstable legacy source evidence")
    return first, before_fd


def _ensure_output(output_dir: Path, persistent_root: Path) -> Path:
    if output_dir.is_symlink():
        raise ValueError("symlinked output directory")
    root = persistent_root.resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("invalid persistent root")
    destination = output_dir.resolve()
    if destination == root or root in destination.parents:
        raise ValueError("recovery output inside live persistent root")
    output_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ValueError("unsafe output directory")
    info = output_dir.stat()
    if (info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise ValueError("output directory is not private")
    return output_dir


def create_archive(
    sources: dict[str, Path], output_dir: Path, *,
    persistent_root: Path,
) -> dict[str, object]:
    """Snapshot explicit legacy filenames with no writes to live source paths."""
    root = persistent_root.resolve(strict=True)
    if not root.is_dir() or not sources or len(sources) > 16:
        raise ValueError("invalid persistent root or source inventory")
    output = _ensure_output(output_dir, persistent_root)
    records: dict[str, dict[str, object]] = {}
    payload: dict[str, bytes] = {}
    absent: list[str] = []
    identities: set[tuple[int, int]] = set()
    source_identities: dict[str, tuple[int, int, int, int, int]] = {}
    total = 0
    for label, candidate in sorted(sources.items()):
        if not isinstance(label, str) or not LABEL.fullmatch(label):
            raise ValueError("invalid recovery source label")
        source = Path(candidate)
        if not source.is_absolute() or ".." in source.parts:
            raise ValueError("legacy path must be absolute")
        read = _read_stable_file(source)
        if read is None:
            absent.append(label)
            continue
        raw, stats = read
        inode = (stats.st_dev, stats.st_ino)
        if inode in identities:
            raise ValueError("duplicate legacy source inode")
        identities.add(inode)
        source_identities[label] = _identity(stats)
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("legacy source budget exceeded")
        resolved = source.resolve(strict=True)
        records[label] = {
            "bytes": len(raw),
            "sha256": _sha(raw),
            "source_path": str(source),
            "inside_persistent_root": resolved == root or root in resolved.parents,
        }
        payload["legacy/" + label] = raw
    if not records:
        raise ValueError("no legacy bytes found: default-path absence is not proof")
    # A stable per-file read is insufficient if a second source changes while
    # other files are inventoried. Recheck bytes and inode from every captured
    # path before committing a manifest. This is NOT cross-store atomicity.
    for label, details in sorted(records.items()):
        reread = _read_stable_file(Path(str(details["source_path"])))
        if (reread is None
                or reread[0] != payload["legacy/" + label]
                or _identity(reread[1]) != source_identities[label]):
            raise ValueError("legacy source changed across capture passes")
    manifest = {
        "format_version": 1,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "files": records,
        "missing_source_labels": absent,
        "source_files_unchanged": True,
        "account_scope_provenance_verified": False,
        "legacy_path_inventory_complete": False,
        "off_host_custody_verified": False,
        "isolated_restore_verified": False,
        "cross_store_atomicity_verified": False,
        "broker_reconciliation_verified": False,
        "trading_authorized": False,
    }
    metadata = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    if len(metadata) > MAX_MANIFEST_BYTES:
        raise ValueError("legacy manifest too large")
    archive = output / (
        "nija-legacy-state-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-" + secrets.token_hex(6) + ".zip"
    )
    original_umask = os.umask(0o077)
    try:
        try:
            with zipfile.ZipFile(archive, mode="x", compression=zipfile.ZIP_DEFLATED) as saved:
                for key, value in sorted(payload.items()):
                    saved.writestr(key, value)
                saved.writestr("manifest.json", metadata)
            archive.chmod(0o600)
            with archive.open("rb") as stream:
                os.fsync(stream.fileno())
        except Exception:
            archive.unlink(missing_ok=True)
            raise
    finally:
        os.umask(original_umask)
    digest = _sha(archive.read_bytes())
    verify = verify_archive(archive, expected_sha256=digest)
    if verify["files_verified"] != len(records):
        raise ValueError("archive readback inventory mismatch")
    return {
        "archive": str(archive),
        "archive_sha256": digest,
        "files_preserved": len(records),
        "missing_source_labels": absent,
        "off_host_custody_verified": False,
        "isolated_restore_verified": False,
        "trading_authorized": False,
    }


def verify_archive(archive: Path, *, expected_sha256: str) -> dict[str, object]:
    """Check pinned archive bytes without ever extracting onto a live filesystem."""
    if not isinstance(expected_sha256, str) or not re.fullmatch(
        r"[0-9a-fA-F]{64}", expected_sha256
    ):
        raise ValueError("expected 64-character SHA-256 required")
    if archive.is_symlink():
        raise ValueError("symlinked archive")
    fd = os.open(archive, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as handle:
        prior = os.fstat(handle.fileno())
        if not stat.S_ISREG(prior.st_mode) or prior.st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("unsafe or oversized archive")
        raw = handle.read(MAX_ARCHIVE_BYTES + 1)
        later = os.fstat(handle.fileno())
    if (len(raw) > MAX_ARCHIVE_BYTES or len(raw) != prior.st_size
            or _identity(prior) != _identity(later)
            or _sha(raw).lower() != expected_sha256.lower()):
        raise ValueError("archive SHA-256 or source changed")
    with zipfile.ZipFile(io.BytesIO(raw)) as source:
        info = source.infolist()
        names = [f.filename for f in info]
        if len(set(names)) != len(names) or len(info) > 17:
            raise ValueError("duplicate or excessive archive members")
        if (sum(f.file_size for f in info) > MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES
                or any(f.is_dir() or f.flag_bits & 1
                       or stat.S_ISLNK(f.external_attr >> 16)
                       or f.file_size > MAX_FILE_BYTES for f in info)):
            raise ValueError("unsafe archive member")
        if "manifest.json" not in names:
            raise ValueError("missing archive manifest")
        metadata = source.read("manifest.json")
        if len(metadata) > MAX_MANIFEST_BYTES:
            raise ValueError("oversized archive manifest")
        manifest = json.loads(metadata, object_pairs_hook=_unique_json_keys)
        if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
            raise ValueError("invalid archive manifest")
        files = manifest.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError("invalid archived file inventory")
        if set(names) != {"manifest.json"} | {"legacy/" + label for label in files}:
            raise ValueError("archive/manifest membership mismatch")
        for label, entry in files.items():
            if not LABEL.fullmatch(label) or not isinstance(entry, dict):
                raise ValueError("unsafe legacy file label or record")
            data = source.read("legacy/" + label)
            if (entry.get("bytes") != len(data)
                    or entry.get("sha256") != _sha(data)):
                raise ValueError("legacy archive member hash mismatch")
        if any(manifest.get(key) is not False for key in (
            "account_scope_provenance_verified", "legacy_path_inventory_complete",
            "off_host_custody_verified", "isolated_restore_verified",
            "cross_store_atomicity_verified", "broker_reconciliation_verified",
            "trading_authorized",
        )):
            raise ValueError("archive contains forbidden recovery certification claims")
    return {
        "archive_sha256_matched": True,
        "files_verified": len(files),
        "off_host_custody_verified": False,
        "isolated_restore_verified": False,
        "trading_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    save = sub.add_parser("snapshot")
    save.add_argument("--persistent-root", type=Path, default=Path("/data"))
    save.add_argument("--output-dir", type=Path, required=True)
    save.add_argument(
        "--source", action="append", default=[], metavar="LABEL=/absolute/path",
        help="additional exact legacy file path from verified runtime diagnostics",
    )
    check = sub.add_parser("verify")
    check.add_argument("--archive", type=Path, required=True)
    check.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.operation == "verify":
            report = verify_archive(args.archive, expected_sha256=args.expected_sha256)
        else:
            sources = dict(DEFAULT_SOURCES)
            for source_arg in args.source:
                label, separator, raw_path = source_arg.partition("=")
                if not separator or label in sources:
                    raise ValueError("invalid or duplicate source override")
                sources[label] = Path(raw_path)
            report = create_archive(
                sources, args.output_dir, persistent_root=args.persistent_root
            )
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({
            "status": "FAILED_CLOSED", "error_type": type(exc).__name__,
            "off_host_custody_verified": False, "trading_authorized": False,
        }, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
