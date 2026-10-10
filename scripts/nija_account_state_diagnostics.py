#!/usr/bin/env python3
"""Read-only account-state inventory and migration planning; never performs cutover."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path
from typing import Any


def _safe_path(path: Path) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("absolute_path_required")
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError("unexpected_symlink")
    return path


def _fingerprint(path: Path) -> dict[str, Any]:
    _safe_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("regular_file_required")
        digest = hashlib.sha256()
        size = 0
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
        after = os.fstat(stream.fileno())
    if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ):
        raise ValueError("source_changed_during_inventory")
    return {"bytes": size, "sha256": digest.hexdigest()}


def _mounts(mountinfo: Path = Path("/proc/self/mountinfo")) -> list[dict[str, str]]:
    output = []
    for line in mountinfo.read_text().splitlines():
        fields = line.split()
        separator = fields.index("-")
        mountpoint = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[4])
        output.append({
            "mountpoint": mountpoint,
            "device": fields[2],
            "filesystem": fields[separator + 1],
        })
    return output


def _files(root: Path) -> list[Path]:
    _safe_path(root)
    if not root.is_dir():
        raise ValueError("inventory_directory_missing")
    output = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = _safe_path(Path(directory) / name)
            if path.is_file():
                output.append(path)
            elif not path.is_dir():
                raise ValueError("unexpected_special_file")
    return sorted(output)


def inventory(
    positions: Path, entries: Path, disk: Path,
    mountinfo: Path = Path("/proc/self/mountinfo"),
    evidence: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Hash source bytes without reading account contents into the report."""
    roots = {"positions": _safe_path(positions), "entry_prices": _safe_path(entries), "disk": _safe_path(disk)}
    if len(set(roots.values())) != 3 or any(
        a in b.parents for key, a in roots.items() for other, b in roots.items()
        if key != other and key != "disk"
    ):
        raise ValueError("inventory_root_scope_mixup")
    records = []
    for kind, root in roots.items():
        for path in _files(root):
            records.append({"kind": kind, "relative": str(path.relative_to(root)), **_fingerprint(path)})
    evidence_files = set()
    for path in evidence:
        _safe_path(path)
        evidence_files.add(path)
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(path) + suffix)
            _safe_path(sidecar)
            if sidecar.exists():
                evidence_files.add(sidecar)
    for path in sorted(evidence_files):
        records.append({"kind": "evidence", "relative": str(path), **_fingerprint(path)})
    # An active writer can invalidate a byte manifest. Do not claim an atomic
    # SQLite/WAL or cross-file snapshot, even when these two reads agree.
    for record in records:
        path = Path(record["relative"]) if record["kind"] == "evidence" else roots[record["kind"]] / record["relative"]
        if _fingerprint(path) != {key: record[key] for key in ("bytes", "sha256")}:
            raise ValueError("source_changed_during_inventory")
    for kind, root in roots.items():
        if {str(p.relative_to(root)) for p in _files(root)} != {
            r["relative"] for r in records if r["kind"] == kind
        }:
            raise ValueError("source_set_changed_during_inventory")
    return {
        "version": 1, "status": "read_only_inventory",
        "roots": {key: str(value) for key, value in roots.items()},
        "evidence": [str(path) for path in evidence],
        "mounts": _mounts(mountinfo), "files": records,
        "atomic_snapshot_verified": False, "backup_restore_verified": False,
        "restart_persistence_verified": False, "historical_pnl_verified": False,
        "observation_allowed": False, "mutations_performed": False,
    }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("duplicate_json_key_or_symbol")
        output[key] = value
    return output


def _read_json(path: Path) -> Any:
    _safe_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, encoding="utf-8") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("regular_file_required")
        return json.load(stream, object_pairs_hook=_unique_object)


def _scope(scope: Any) -> str:
    if not isinstance(scope, str) or not re.fullmatch(
        r"(?:platform|user__[a-z0-9][a-z0-9._-]*)__(?:coinbase|kraken|okx|alpaca|binance)", scope
    ) or "unknown" in scope or scope.count("__") not in (1, 2):
        raise ValueError("missing_or_ambiguous_account_scope")
    return scope


def _check_basis(path: Path, kind: str) -> None:
    payload = _read_json(path)
    rows = payload.get("positions") if kind == "positions" and isinstance(payload, dict) else payload
    if not isinstance(rows, dict) or not rows:
        raise ValueError("empty_or_invalid_account_state")
    symbols = set()
    for symbol, row in rows.items():
        normalized = str(symbol).strip().upper().replace("/", "-").replace("_", "-")
        if not normalized or normalized in symbols:
            raise ValueError("duplicate_or_missing_symbol")
        symbols.add(normalized)
        if not isinstance(row, dict):
            raise ValueError("invalid_account_record")
        price = row.get("entry_price" if kind == "positions" else "price")
        quantity = row.get("quantity")
        source = row.get("entry_price_source" if kind == "positions" else "source")
        if (
            isinstance(price, bool) or isinstance(quantity, bool)
            or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0
            or not isinstance(quantity, (int, float)) or not math.isfinite(quantity) or quantity <= 0
            or source not in {"execution", "broker_fill", "reconstructed_verified_cost_basis"}
            or (kind == "positions" and row.get("cost_basis_verified") is not True)
        ):
            raise ValueError("untrusted_cost_basis")


def dry_run(
    manifest: dict[str, Any], scopes: dict[str, str], backup_review: str,
    mountinfo: Path = Path("/proc/self/mountinfo"),
) -> dict[str, Any]:
    """Compare a reviewed manifest and plan only; local labels are not broker proof."""
    if not backup_review.strip():
        raise ValueError("backup_review_reference_required")
    if manifest.get("version") != 1:
        raise ValueError("unsupported_manifest")
    roots = manifest["roots"]
    evidence = tuple(Path(path) for path in manifest.get("evidence", ()))
    current = inventory(*(Path(roots[key]) for key in ("positions", "entry_prices", "disk")), mountinfo, evidence)
    if current["files"] != manifest["files"]:
        raise ValueError("checksum_or_file_set_mismatch_including_wal")
    disk = _safe_path(Path(roots["disk"]))
    if disk != Path("/data") or not any(
        m["mountpoint"] == str(disk) and m["filesystem"] not in {"tmpfs", "ramfs", "overlay"}
        for m in current["mounts"]
    ):
        raise ValueError("persistent_data_mount_not_verified")
    targets = {"positions": disk / "positions", "entry_prices": disk / "entry_prices"}
    for kind, target in targets.items():
        _safe_path(target)
        configured = os.environ.get(
            "NIJA_ACCOUNT_POSITION_STATE_DIR" if kind == "positions" else "NIJA_ACCOUNT_ENTRY_PRICE_STATE_DIR"
        )
        if configured and _safe_path(Path(configured)) != target:
            raise ValueError("configured_state_path_not_on_target_mount")
        if target == Path(roots[kind]):
            raise ValueError("source_destination_mixup")
        if any(
            Path(m["mountpoint"]) == target or target in Path(m["mountpoint"]).parents
            for m in current["mounts"] if m["mountpoint"] != str(disk)
        ):
            raise ValueError("nested_mount_mixup")
    planned = []
    kinds_by_scope: dict[str, set[str]] = {}
    used_scopes = set()
    for record in current["files"]:
        kind = record["kind"]
        if kind in {"disk", "evidence"}:
            continue
        name = record["relative"]
        scope = _scope(scopes.get(name))
        if name != scope + ".json":
            raise ValueError("filename_scope_mixup")
        used_scopes.add(name)
        kinds_by_scope.setdefault(scope, set()).add(kind)
        source = Path(roots[kind]) / name
        _check_basis(source, kind)
        destination = _safe_path(targets[kind] / name)
        if destination.exists():
            raise ValueError("destination_collision_no_overwrite")
        planned.append({"kind": kind, "scope": scope, "source": str(source),
                        "destination": str(destination), **{k: record[k] for k in ("bytes", "sha256")}})
    if not planned:
        raise ValueError("empty_migration")
    if used_scopes != set(scopes) or any(kinds != set(targets) for kinds in kinds_by_scope.values()):
        raise ValueError("missing_or_ambiguous_account_scope")
    # Detect a file change while JSON validation was in progress.
    if inventory(
        *(Path(roots[key]) for key in ("positions", "entry_prices", "disk")), mountinfo, evidence
    )["files"] != current["files"]:
        raise ValueError("source_changed_during_dry_run")
    return {
        "status": "dry_run_only", "planned": planned, "mutations_performed": False,
        "backup_review_reference_supplied": True,
        "backup_restore_verified": False, "wal_integrity_verified": False,
        "broker_authenticated_reconciliation_verified": False,
        "migration_integrity_verified": False, "restart_persistence_verified": False,
        "protective_exit_verified": False, "historical_pnl_verified": False,
        "fresh_execution_proof_verified": False, "observation_allowed": False,
    }


def main() -> int:
    """Run explicit inventory or opt-in planning without importing the trading runtime."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positions", type=Path, default=Path("/app/data/positions"))
    parser.add_argument("--entry-prices", type=Path, default=Path("/app/data/entry_prices"))
    parser.add_argument("--disk", type=Path, default=Path("/data"))
    parser.add_argument("--evidence", type=Path, action="append", default=[],
                        help="explicit ledger, journal or pending fill proof file; hashes SQLite sidecars too")
    parser.add_argument("--migration-dry-run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--scopes", type=Path)
    parser.add_argument("--backup-review", default="")
    opts = parser.parse_args()
    try:
        if opts.migration_dry_run:
            if not opts.manifest or not opts.scopes:
                raise ValueError("reviewed_manifest_and_scope_registry_required")
            result = dry_run(_read_json(opts.manifest), _read_json(opts.scopes), opts.backup_review)
        else:
            if opts.manifest or opts.scopes or opts.backup_review:
                raise ValueError("explicit_migration_dry_run_required")
            result = inventory(opts.positions, opts.entry_prices, opts.disk, evidence=tuple(opts.evidence))
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "error_type": type(exc).__name__,
                          "mutations_performed": False, "observation_allowed": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
