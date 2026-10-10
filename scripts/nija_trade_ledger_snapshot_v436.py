#!/usr/bin/env python3
"""Create and verify a read-only SQLite ledger snapshot before Render migration.

This script does not submit trades, contact brokers, alter the source ledger,
change runtime flags, or declare that a local backup survived a redeploy.

Run it INSIDE THE CURRENT LIVE CONTAINER, before attaching a Render disk.
Copy the resulting encrypted-transport archive off the host with SCP/SFTP,
then use the verify subcommand against the independently saved copy.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import gzip
import stat
import io
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any


CHUNK_SIZE = 1024 * 1024
MAX_COMPANION_BYTES = 128 * 1024 * 1024
MAX_SQLITE_BYTES = 2 * 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MANDATORY_TABLES = ("trade_ledger", "open_positions", "completed_trades")
OPTIONAL_FILES = (
    ("pending_kraken_fills.json", "NIJA_KRAKEN_PENDING_FILL_PROOF_PATH",
     "./data/kraken_pending_fill_proof.json"),
    ("execution_journal.jsonl", "NIJA_EXECUTION_JOURNAL_PATH",
     "./data/execution_journal.jsonl"),
    ("open_positions.json", "NIJA_POSITIONS_FILE",
     "./data/open_positions.json"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = [
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    output: dict[str, int] = {}
    for table in sorted(tables):
        # Identifiers originate in sqlite_master, not user input. Quote safely.
        safe_name = '"' + table.replace('"', '""') + '"'
        output[table] = int(
            connection.execute("SELECT COUNT(*) FROM " + safe_name).fetchone()[0]
        )
    return output


def _validate_database(path: Path) -> dict[str, int]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("snapshot SQLite file missing or is a symlink")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=15)
    try:
        check = connection.execute("PRAGMA integrity_check").fetchall()
        if check != [("ok",)]:
            raise RuntimeError("SQLite integrity_check did not return ok")
        tables = _counts(connection)
        missing = set(MANDATORY_TABLES) - set(tables)
        if missing:
            raise RuntimeError("trading-ledger tables missing: " + ",".join(sorted(missing)))
        return tables
    finally:
        connection.close()


def _snapshot_sqlite(source: Path, destination: Path) -> dict[str, int]:
    if not source.is_file() or source.is_symlink():
        raise FileNotFoundError("source SQLite ledger is missing or is a symlink")
    if source.resolve() == destination.resolve():
        raise ValueError("source and destination cannot be the same file")
    # Online SQLite backup API captures one transactional snapshot, including
    # records residing in a WAL, without modifying the source connection.
    reader = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=15)
    writer = sqlite3.connect(str(destination), timeout=15)
    try:
        reader.backup(writer, pages=256, sleep=0.1)
        writer.commit()
    finally:
        writer.close()
        reader.close()
    return _validate_database(destination)


def _copy_companion(source: Path, destination: Path) -> bool:
    if not source.is_file() or source.is_symlink():
        return False
    before = source.stat()
    if before.st_size > MAX_COMPANION_BYTES:
        raise ValueError("companion file exceeds maximum safe snapshot size")
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing, length=CHUNK_SIZE)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    after = source.stat()
    # A changing JSONL/journal requires a further quiescent backup. We still
    # preserve the copied evidence but must NOT mark the set fully consistent.
    return (
        before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
        and destination.stat().st_size == before.st_size
    )


def create_snapshot(source: Path, output_dir: Path) -> dict[str, Any]:
    """Create an integrity-checked local archive; require an off-host copy."""
    os.umask(0o077)
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ValueError("unsafe output directory")
    with tempfile.TemporaryDirectory(prefix="nija-ledger-stage-", dir=output_dir) as stage:
        stage_dir = Path(stage)
        ledger_copy = stage_dir / "trade_ledger.db"
        counts = _snapshot_sqlite(source, ledger_copy)
        members: dict[str, dict[str, Any]] = {}
        sources = [("trade_ledger.db", ledger_copy, True)]
        companions_stable = True
        missing_companions: list[str] = []
        for name, variable, fallback in OPTIONAL_FILES:
            candidate = Path(os.getenv(variable) or fallback)
            destination = stage_dir / name
            if not candidate.is_file() or candidate.is_symlink():
                missing_companions.append(name)
                continue
            stable = _copy_companion(candidate, destination)
            companions_stable = companions_stable and stable
            sources.append((name, destination, stable))
        for name, file, stable in sources:
            members[name] = {
                "bytes": file.stat().st_size,
                "sha256": _sha256(file),
                "read_stable": stable,
            }
        manifest = {
            "format_version": 1,
            "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source_is_not_mutated": True,
            "snapshot_sqlite_integrity_ok": True,
            "sqlite_tables": counts,
            "members": members,
            "missing_companions": missing_companions,
            "companions_stable": companions_stable,
            "off_host_backup_verified": False,
            "restore_test_verified": False,
            "historical_fill_completeness_verified": False,
            "restart_persistence_verified": False,
        }
        manifest_file = stage_dir / "manifest.json"
        manifest_file.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        identity = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = os.urandom(5).hex()
        final_name = "nija-trading-ledger-" + identity + "-" + suffix + ".tar.gz"
        temp_path = output_dir / (final_name + ".part")
        archive_path = output_dir / final_name
        try:
            with tarfile.open(temp_path, mode="w:gz") as archive:
                for name in sorted(members):
                    archive.add(stage_dir / name, arcname=name, recursive=False)
                archive.add(manifest_file, arcname="manifest.json", recursive=False)
            with temp_path.open("rb") as stream:
                os.fsync(stream.fileno())
            temp_path.replace(archive_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
    verified = verify_snapshot(archive_path)
    result = {
        "archive": str(archive_path),
        "sha256": _sha256(archive_path),
        "archive_bytes": archive_path.stat().st_size,
        "verified_sqlite_tables": verified["sqlite_tables"],
        "companions_stable": verified["companions_stable"],
        "off_host_backup_verified": False,
        "restore_test_verified": False,
        "ACTION_REQUIRED": "Copy archive off this Render instance using SCP/SFTP before redeploy.",
    }
    return result


def _tar_octal(field: bytes) -> int:
    """Accept only ordinary POSIX octal sizes, never GNU base-256 overrides."""
    raw = field.strip(b"\x00 ")
    if not raw or any(char not in b"01234567" for char in raw):
        raise ValueError("unsafe tar header numeric field")
    return int(raw, 8)


def _verify_tar_header(block: bytes) -> tuple[str, int, bytes]:
    if len(block) != 512:
        raise ValueError("truncated tar header")
    checksum = _tar_octal(block[148:156])
    signed = sum(block[:148] + b"        " + block[156:])
    if signed != checksum:
        raise ValueError("tar header checksum invalid")
    if block[257:263] not in (b"ustar\x00", b"ustar "):
        raise ValueError("unsupported tar header format")
    if block[345:500].strip(b"\x00 ") != b"":
        raise ValueError("archive contains prefixed or nested path")
    name_bytes = block[:100].split(b"\x00", 1)[0]
    try:
        name = name_bytes.decode("ascii")
    except UnicodeError as exc:
        raise ValueError("archive contains non-ascii member name") from exc
    return name, _tar_octal(block[124:136]), block[156:157]


def _verify_pax_metadata(raw: bytes) -> None:
    """Permit timestamps only, not name/size/owner/link overrides."""
    at = 0
    while at < len(raw):
        space = raw.find(b" ", at)
        if space <= at:
            raise ValueError("invalid pax metadata")
        length_str = raw[at:space]
        if not length_str.isdigit() or len(length_str) > 8:
            raise ValueError("invalid pax record length")
        length = int(length_str)
        end = at + length
        if length <= space - at or end > len(raw) or raw[end - 1:end] != b"\n":
            raise ValueError("invalid pax record bounds")
        entry = raw[space + 1:end - 1]
        key, sep, _value = entry.partition(b"=")
        if not sep or key not in {b"mtime", b"atime", b"ctime"}:
            raise ValueError("unsafe pax metadata override")
        at = end


def _unpack_bounded_archive(archive_path: Path, stage_dir: Path) -> tuple[str, ...]:
    """Single-pass gzip/tar decoder: bound headers BEFORE allocating member data.

    Unlike tarfile.getmembers()/TarInfo._proc_pax, this never parses an
    attacker-declared multi-gigabyte PAX record in memory. Generated snapshots
    contain only known regular basenames and optional short timestamp PAX.
    """
    limits = {"trade_ledger.db": MAX_SQLITE_BYTES, "manifest.json": MAX_MANIFEST_BYTES}
    limits.update({name: MAX_COMPANION_BYTES for name, _, _ in OPTIONAL_FILES})
    max_members = len(limits)
    max_headers = max_members * 2 + 2
    max_tar_bytes = sum(limits.values()) + (max_headers + 2) * (512 + 16384)
    total_read = 0

    with gzip.open(archive_path, "rb") as compressed:
        def exact(count: int) -> bytes:
            nonlocal total_read
            if count < 0 or total_read + count > max_tar_bytes:
                raise ValueError("decompressed tar byte limit exceeded")
            chunks: list[bytes] = []
            remaining = count
            while remaining:
                part = compressed.read(min(remaining, CHUNK_SIZE))
                if not part:
                    raise ValueError("truncated archive")
                total_read += len(part)
                remaining -= len(part)
                chunks.append(part)
            return b"".join(chunks)

        entries: set[str] = set()
        metadata_headers = 0
        while True:
            header = exact(512)
            if header == b"\x00" * 512:
                if exact(512) != b"\x00" * 512:
                    raise ValueError("invalid tar end marker")
                # tarfile writes up to 10KB zero end-record padding.
                trailing = 0
                while True:
                    block = compressed.read(CHUNK_SIZE)
                    if not block:
                        break
                    trailing += len(block)
                    if trailing > 65536 or any(block):
                        raise ValueError("unexpected tar trailing data")
                break

            name, size, kind = _verify_tar_header(header)
            if kind == b"x":
                metadata_headers += 1
                if (metadata_headers > max_members or size > 16384
                        or name != "././@PaxHeader"):
                    raise ValueError("unsafe or oversized pax header")
                _verify_pax_metadata(exact(size))
                padding = (-size) % 512
                if padding:
                    exact(padding)
                continue
            if kind not in (b"0", b"\x00"):
                raise ValueError("archive contains nonregular member")
            if name not in limits or name in entries or size > limits[name]:
                raise ValueError("archive has unsafe, duplicate or oversized member")
            if name == "trade_ledger.db" and size == 0:
                raise ValueError("archive contains empty trading ledger")
            entries.add(name)
            if len(entries) > max_members:
                raise ValueError("archive has too many members")
            # Stream directly to private temporary files; never buffer SQLite
            # in RAM. Each read is bounded and the tar reader tracks total bytes.
            remaining = size
            with (stage_dir / name).open("xb") as output:
                while remaining:
                    take = min(CHUNK_SIZE, remaining)
                    output.write(exact(take))
                    remaining -= take
            padding = (-size) % 512
            if padding:
                exact(padding)
            if len(entries) + metadata_headers > max_headers:
                raise ValueError("archive metadata header limit exceeded")

    if not {"manifest.json", "trade_ledger.db"}.issubset(entries):
        raise ValueError("manifest or trading ledger missing")
    return tuple(sorted(entries))


def verify_snapshot(
    archive_path: Path, *, expected_sha256: str | None = None,
    exercise_restore: bool = False,
) -> dict[str, Any]:
    """Pin source bytes once, then bounded-decode and test only an isolated copy.

    Archive validity and a disposable restore never establish independently
    retained off-host storage or complete historical broker accounting.
    """
    if not archive_path.is_file() or archive_path.is_symlink():
        raise ValueError("archive missing or is a symlink")
    expected: str | None = None
    if expected_sha256 is not None:
        expected = str(expected_sha256).strip().lower()
        if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
            raise ValueError("expected archive SHA-256 must be 64 hex characters")

    # Checksum and parsing operate on the SAME private immutable staged bytes.
    # Open once with O_NOFOLLOW so a symlink swap cannot redirect the source.
    with tempfile.TemporaryDirectory(prefix="nija-ledger-verify-") as stage:
        stage_dir = Path(stage)
        staged_archive = stage_dir / "_pinned_source.tar.gz"
        fd = os.open(str(archive_path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            with os.fdopen(fd, "rb") as original, staged_archive.open("xb") as output:
                source_stat = os.fstat(original.fileno())
                max_compressed = (
                    MAX_SQLITE_BYTES + MAX_MANIFEST_BYTES
                    + len(OPTIONAL_FILES) * MAX_COMPANION_BYTES + 2 * 1024 * 1024
                )
                if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_size > max_compressed:
                    raise ValueError("unsafe or oversized source archive")
                digest = hashlib.sha256()
                total = 0
                while True:
                    chunk = original.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_compressed:
                        raise ValueError("archive compressed-size limit exceeded")
                    digest.update(chunk)
                    output.write(chunk)
                if total != source_stat.st_size:
                    raise ValueError("source archive changed during snapshot")
        except BaseException:
            # os.fdopen owns the descriptor once opened; close only if
            # construction failed before ownership was transferred.
            if not staged_archive.exists():
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise
        if expected is not None and digest.hexdigest() != expected:
            raise ValueError("off-host archive SHA-256 does not match source")

        names = set(_unpack_bounded_archive(staged_archive, stage_dir))
        manifest_raw = (stage_dir / "manifest.json").read_bytes()
        manifest = json.loads(manifest_raw.decode("utf-8"))
        if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
            raise ValueError("unsupported snapshot format")
        tracked = manifest.get("members")
        if not isinstance(tracked, dict) or names != (set(tracked) | {"manifest.json"}):
            raise ValueError("archive inventory does not match manifest")
        for name, record in tracked.items():
            if not isinstance(record, dict):
                raise ValueError("malformed archive member metadata")
            declared_size, declared_sha = record.get("bytes"), record.get("sha256")
            if (type(declared_size) is not int or not isinstance(declared_sha, str)
                    or len(declared_sha) != 64
                    or any(ch not in "0123456789abcdef" for ch in declared_sha.lower())
                    or declared_size != (stage_dir / name).stat().st_size):
                raise ValueError("snapshot manifest size mismatch or digest invalid: " + name)
            if _sha256(stage_dir / name) != declared_sha.lower():
                raise ValueError("snapshot member digest mismatch: " + name)
        counts = _validate_database(stage_dir / "trade_ledger.db")
        if counts != manifest.get("sqlite_tables"):
            raise ValueError("SQLite counts do not match manifest")

        if exercise_restore:
            restored = stage_dir / "_isolated_restore.db"
            reader = sqlite3.connect(
                (stage_dir / "trade_ledger.db").resolve().as_uri() + "?mode=ro",
                uri=True, timeout=15,
            )
            writer = sqlite3.connect(str(restored), timeout=15)
            try:
                reader.execute("PRAGMA query_only=ON")
                reader.backup(writer, pages=256, sleep=0.1)
                writer.commit()
            finally:
                writer.close()
                reader.close()
            if _validate_database(restored) != counts:
                raise ValueError("isolated restore did not preserve table counts")
    result = dict(manifest)
    if exercise_restore:
        result["isolated_restore_test_verified"] = True
        result["off_host_backup_verified"] = False
        result["historical_fill_completeness_verified"] = False
        result["live_trading_eligible"] = False
    if expected is not None:
        result["expected_archive_sha256_matched"] = True
    return result


def main() -> int:
    """Parse CLI arguments; only create read-only snapshots or verify copies."""
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    backup = actions.add_parser("backup", help="Create verified local snapshot")
    backup.add_argument(
        "--source",
        default=os.getenv("NIJA_TRADE_LEDGER_DB_PATH", "./data/trade_ledger.db"),
    )
    backup.add_argument("--output-dir", required=True)
    check = actions.add_parser("verify", help="Verify archive copied off host")
    check.add_argument("--archive", required=True)
    restoration = actions.add_parser(
        "restore-test", help="Verify hash and restore off-host copy in disposable storage"
    )
    restoration.add_argument("--archive", required=True)
    restoration.add_argument(
        "--expected-sha256", required=True,
        help="archive digest recorded on the original host before transfer",
    )
    args = parser.parse_args()
    try:
        if args.action == "backup":
            result = create_snapshot(Path(args.source), Path(args.output_dir))
        elif args.action == "verify":
            manifest = verify_snapshot(Path(args.archive))
            result = {
                "integrity": "verified",
                "sqlite_tables": manifest["sqlite_tables"],
                "off_host_backup_verified": False,
                "restore_test_verified": False,
                "NOTE": "Verify an independent off-host copy, not the live container copy.",
            }
        else:
            manifest = verify_snapshot(
                Path(args.archive),
                expected_sha256=args.expected_sha256,
                exercise_restore=True,
            )
            result = {
                "integrity": "verified",
                "expected_archive_sha256_matched": True,
                "isolated_restore_test_verified": True,
                "sqlite_tables": manifest["sqlite_tables"],
                "off_host_backup_verified": False,
                "historical_fill_completeness_verified": False,
                "live_trading_eligible": False,
                "NOTE": "This validates the supplied copy, not where it is stored or whether "
                        "history is complete; independently attest off-host retention.",
            }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        # Never include database contents or environment secret values in logs.
        print(
            json.dumps({"status": "FAILED_CLOSED", "error_type": type(exc).__name__,
                        "detail": str(exc)[:160]}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
