"""Stage historical broker responses in a new private database, never live accounting.

Preserves original page bytes and links every record to its archived page.
No broker imports/requests, migrations, account assignment, lot allocation,
timestamp renewal, receipt issuance, collector registration or order authority.
Source hashes identify bytes only; they are not independent authentication.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tarfile
import tempfile
from typing import Any

MAX_ARCHIVE = 16 * 1024 * 1024
MAX_PLAIN = 64 * 1024 * 1024
MAX_MEMBER = 1024 * 1024
MAX_RECORDS = 100000
PAGE = re.compile(r"(capture/07_trade_history_|ledger/08_ledger_history_)[0-9]{3}\.json\Z")


class StagingDenied(ValueError):
    """Fixed error codes; never carry archive records, identities or secret values."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise StagingDenied(code)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise StagingDenied("nonfinite_json_number")


def _read_source(path: Path) -> bytes:
    _require(path.is_absolute() and path.resolve(strict=True) == path, "source_path_invalid")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid()
                 and not before.st_mode & 0o022 and 0 < before.st_size <= MAX_ARCHIVE,
                 "source_file_invalid")
        raw = stream.read(MAX_ARCHIVE + 1)
        after = os.fstat(stream.fileno())
    signature = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    _require(signature(before) == signature(after) and len(raw) == before.st_size,
             "source_changed_during_read")
    return raw


def _pages(raw: bytes) -> list[tuple[str, str, bytes, dict[str, Any]]]:
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
        plain = compressed.read(MAX_PLAIN + 1)
    _require(len(plain) <= MAX_PLAIN, "decompressed_archive_limit")
    pages = []
    names = set()
    with tarfile.open(fileobj=io.BytesIO(plain), mode="r:") as archive:
        for index, member in enumerate(archive):
            _require(index < 1000, "archive_member_limit")
            path = PurePosixPath(member.name)
            _require(not path.is_absolute() and ".." not in path.parts and "\\" not in member.name,
                     "archive_path_invalid")
            if member.isdir():
                continue
            _require(member.isfile() and member.name not in names and 0 <= member.size <= MAX_MEMBER,
                     "archive_member_invalid")
            names.add(member.name)
            if PAGE.fullmatch(member.name) is None:
                continue
            handle = archive.extractfile(member)
            _require(handle is not None, "archive_member_unavailable")
            body = handle.read(MAX_MEMBER + 1)
            _require(len(body) == member.size, "archive_member_size_mismatch")
            document = json.loads(body, object_pairs_hook=_unique, parse_constant=_nonfinite)
            _require(type(document) is dict and document.get("error") == []
                     and type(document.get("result")) is dict, "response_envelope_invalid")
            field = "trades" if member.name.startswith("capture/") else "ledger"
            result = document["result"]
            _require(type(result.get(field)) is dict and type(result.get("count")) is int
                     and result["count"] >= 0, "history_page_invalid")
            pages.append((member.name, field, body, result))
    _require({page[1] for page in pages} == {"trades", "ledger"}, "both_history_families_required")
    return sorted(pages, key=lambda page: page[0])


def stage_history(archive_path: Path, output_root: Path) -> dict[str, Any]:
    """Create a new isolated private store; never open an operational ledger for writing.

    The output root must already exist and be private. Every call creates a new
    child directory; it cannot replace a previous recovery or production file.
    Original API timestamps/fields remain in the stored original page bytes.
    Archive completeness, account ownership and current positions are not inferred.
    """
    directory = None
    connection = None
    try:
        raw = _read_source(Path(archive_path))
        pages = _pages(raw)
        root = Path(output_root)
        _require(root.is_absolute() and root.resolve(strict=True) == root, "output_root_invalid")
        info = root.stat()
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid() and not info.st_mode & 0o077,
                 "output_root_not_private")
        directory = Path(tempfile.mkdtemp(prefix="archived-capture-", dir=root))
        database = directory / "historical_broker_records.sqlite3"
        descriptor = os.open(database, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(descriptor)
        connection = sqlite3.connect(database)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript("""
            CREATE TABLE source_archive (sha256 TEXT PRIMARY KEY, origin TEXT NOT NULL,
                account_identity_verified INTEGER NOT NULL CHECK(account_identity_verified=0),
                complete_history_verified INTEGER NOT NULL CHECK(complete_history_verified=0),
                current_snapshot_verified INTEGER NOT NULL CHECK(current_snapshot_verified=0),
                authorizes_orders INTEGER NOT NULL CHECK(authorizes_orders=0));
            CREATE TABLE source_page (name TEXT PRIMARY KEY, family TEXT NOT NULL,
                sha256 TEXT NOT NULL, reported_count INTEGER NOT NULL, original_bytes BLOB NOT NULL);
            CREATE TABLE archived_record (family TEXT NOT NULL, record_id TEXT NOT NULL,
                page_name TEXT NOT NULL REFERENCES source_page(name), payload TEXT NOT NULL,
                PRIMARY KEY(family, record_id, page_name));
        """)
        digest = hashlib.sha256(raw).hexdigest()
        connection.execute("INSERT INTO source_archive VALUES (?, ?, 0, 0, 0, 0)",
                           (digest, "historical_broker_response_archive"))
        records: dict[tuple[str, str], str] = {}
        occurrences = 0
        for name, family, body, result in pages:
            connection.execute("INSERT INTO source_page VALUES (?, ?, ?, ?, ?)",
                               (name, family, hashlib.sha256(body).hexdigest(), result["count"], body))
            for identity, value in result[family].items():
                _require(type(identity) is str and 0 < len(identity) <= 128 and identity.isascii()
                         and not any(c.isspace() or ord(c) < 32 for c in identity)
                         and type(value) is dict, "archived_record_invalid")
                payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
                key = (family, identity)
                _require(key not in records or records[key] == payload, "conflicting_archived_record")
                records[key] = payload
                occurrences += 1
                _require(occurrences <= MAX_RECORDS, "archived_record_limit")
                connection.execute("INSERT INTO archived_record VALUES (?, ?, ?, ?)",
                                   (family, identity, name, payload))
        connection.commit()
        _require(connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "staged_integrity_failed")
        _require(connection.execute("SELECT COUNT(*) FROM archived_record").fetchone()[0] == occurrences,
                 "staged_record_count_mismatch")
        counts = {family: sum(key[0] == family for key in records) for family in ("trades", "ledger")}
        connection.close()
        connection = None
        with database.open("rb") as stream:
            os.fsync(stream.fileno())
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return {"status": "historical_capture_staged_not_certified", "database": str(database),
                "source_archive_sha256": digest, "source_page_count": len(pages), "unique_records": counts,
                "duplicate_occurrences": occurrences - len(records),
                "account_identity_verified": False, "complete_history_verified": False,
                "current_snapshot_verified": False, "production_ledger_changed": False,
                "collector_certified": False, "authorizes_orders": False}
    except Exception:
        if connection is not None:
            connection.close()
        if directory is not None:
            shutil.rmtree(directory)
        raise StagingDenied("historical_staging_denied") from None


def main() -> int:
    """Print counts and fixed statuses only, never raw account or record data."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(stage_history(args.archive, args.output_root), sort_keys=True))
        return 0
    except StagingDenied:
        print(json.dumps({"status": "historical_staging_denied", "authorizes_orders": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
