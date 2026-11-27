"""Lead-only SQLite snapshots in a subprocess that cannot open files for writing.

No runtime imports, network, replay, configuration change, or trading access.
Default output contains aggregate evidence only. Archive stdout must be piped
straight into encryption; it contains private records and must never be logged.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
import time
import zipfile

ALLOWED_TABLES = frozenset({
    'website_leads', 'website_lead_crm_sync', 'website_lead_forwarding',
    'website_lead_forward_aliases', 'justcall_webhook_events', 'outreach_calls',
    'outreach_suppressions', 'outreach_autodial_queue', 'outreach_autodial_daily_quota',
    'sqlite_sequence', 'sqlite_stat1', 'sqlite_stat4',
    'outreach_apollo_field_mappings', 'outreach_apollo_sync_state',
})


class Comparison(ctypes.Structure):
    """libseccomp's scmp_arg_cmp ABI."""
    _fields_ = [('arg', ctypes.c_uint), ('op', ctypes.c_int),
                ('datum_a', ctypes.c_uint64), ('datum_b', ctypes.c_uint64)]


def deny_filesystem_writes() -> None:
    """Apply a nonremovable kernel filter before opening any source database."""
    lib = ctypes.CDLL('libseccomp.so.2', use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                         ctypes.c_int, ctypes.c_uint, ctypes.POINTER(Comparison)]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = lib.seccomp_init(0x7fff0000)
    if not ctx:
        raise RuntimeError('sandbox_init_failed')
    action = 0x00050000 | errno.EPERM

    def rule(name: str, comparison: Comparison | None = None, required: bool = False) -> None:
        number = lib.seccomp_syscall_resolve_name(name.encode())
        if number < 0:
            if required:
                raise RuntimeError('required_syscall_unavailable')
            return
        pointer = ctypes.pointer(comparison) if comparison is not None else None
        if lib.seccomp_rule_add_array(ctx, action, number, int(comparison is not None), pointer) != 0:
            raise RuntimeError('sandbox_rule_failed')

    try:
        for name, arg in (('open', 1), ('openat', 2)):
            for flag in (os.O_WRONLY, os.O_RDWR, os.O_CREAT, os.O_TRUNC, os.O_APPEND):
                rule(name, Comparison(arg, 7, flag, flag), required=name == 'openat')
        for name in (
            'openat2', 'creat', 'truncate', 'ftruncate', 'unlink', 'unlinkat',
            'rename', 'renameat', 'renameat2', 'mkdir', 'mkdirat', 'rmdir',
            'link', 'linkat', 'symlink', 'symlinkat', 'mknod', 'mknodat',
            'chmod', 'fchmod', 'fchmodat', 'chown', 'fchown', 'lchown', 'fchownat',
            'utime', 'utimes', 'utimensat', 'futimesat', 'setxattr', 'lsetxattr',
            'fsetxattr', 'removexattr', 'lremovexattr', 'fremovexattr',
            'mount', 'umount2', 'io_uring_setup', 'open_by_handle_at',
            'socket', 'connect', 'execve', 'execveat',
        ):
            rule(name)
        if lib.seccomp_load(ctx) != 0:
            raise RuntimeError('sandbox_load_failed')
    finally:
        lib.seccomp_release(ctx)
    # Fail closed before any source open if the filter does not actually deny
    # creation. This self-test never targets a production data/configuration path.
    probe = f'/tmp/nija-lead-write-denial-{os.getpid()}'
    try:
        descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except PermissionError:
        return
    else:
        os.close(descriptor)
        raise RuntimeError('sandbox_negative_control_failed')


def logical_state(db: sqlite3.Connection) -> dict:
    """Hash every typed row including multiplicity; disclose no row values."""
    tables = [x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    if set(tables) - ALLOWED_TABLES:
        raise RuntimeError('unknown_or_nonlead_table_requires_review')
    schema = db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
    result = {'schema_sha256': hashlib.sha256(json.dumps(schema).encode()).hexdigest(), 'tables': {}}
    for table in sorted(tables):
        rows = db.execute('SELECT * FROM "' + table + '"').fetchall()
        typed = [json.dumps([
            ['blob', base64.b64encode(v).decode()] if isinstance(v, bytes)
            else [type(v).__name__, v] for v in row
        ], ensure_ascii=True, separators=(',', ':')) for row in rows]
        digest = hashlib.sha256(json.dumps(sorted(typed)).encode()).hexdigest()
        result['tables'][table] = {'rows': len(rows), 'content_sha256_private': digest}
    return result


def capture(paths: list[Path]) -> tuple[dict, bytes]:
    """Take online backups at an overlapping source read-transaction boundary."""
    if not 1 <= len(paths) <= 2 or len(set(paths)) != len(paths):
        raise ValueError('invalid_source_inventory')
    for path in paths:
        if not path.is_absolute() or path.name not in ('nija_outreach.sqlite3', 'nija_lead_forwarding.sqlite3'):
            raise ValueError('source_path_not_lead_allowlist')
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
            raise ValueError('source_missing_or_symlink')
        if path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError('source_exceeds_capture_bound')
        if any(Path(str(path) + s).exists() for s in ('-wal', '-shm', '-journal')):
            raise ValueError('active_sidecar_requires_review')
        with path.open('rb') as source:
            header = source.read(100)
        if len(header) != 100 or header[:16] != b'SQLite format 3' + bytes([0]) or header[18:20] != bytes([1, 1]):
            raise ValueError('source_not_verified_rollback_mode')
    deny_filesystem_writes()
    sources = []
    try:
        # All read transactions remain open through both captures. In rollback
        # mode, shared read locks establish a common stable source interval.
        for path in paths:
            source = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)
            sources.append(source)
            source.execute('PRAGMA query_only=ON')
            source.execute('PRAGMA temp_store=MEMORY')
            source.execute('BEGIN')
            source.execute('SELECT rootpage FROM sqlite_master LIMIT 1').fetchall()
            if source.execute('PRAGMA journal_mode').fetchone()[0] not in ('delete', 'truncate', 'persist'):
                raise RuntimeError('journal_mode_changed')
        manifest = {'captured_at_unix': time.time(), 'sandbox_write_denial_verified': True,
                    'online_backup_api': True, 'production_certified': False, 'databases': {}}
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path, source in zip(paths, sources):
                original = logical_state(source)
                with sqlite3.connect(':memory:') as target:
                    source.backup(target)
                    if target.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                        raise RuntimeError('snapshot_integrity_failed')
                    if logical_state(target) != original:
                        raise RuntimeError('source_snapshot_reconciliation_failed')
                    data = target.serialize()
                manifest['databases'][path.name] = {
                    'source_path': str(path), 'bytes': len(data),
                    'snapshot_sha256': hashlib.sha256(data).hexdigest(), **original,
                }
                archive.writestr(path.name, data)
            archive.writestr('manifest.json', json.dumps(manifest, sort_keys=True))
        return manifest, buffer.getvalue()
    finally:
        for source in sources:
            source.close()


def public_summary(manifest: dict) -> dict:
    """Return counts and snapshot hashes, never record content fingerprints."""
    return {**{k: v for k, v in manifest.items() if k != 'databases'}, 'databases': {
        key: {**{k: v for k, v in value.items() if k not in ('tables', 'schema_sha256')},
              'table_counts': {k: v['rows'] for k, v in value['tables'].items()}}
        for key, value in manifest['databases'].items()
    }}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive-to-encryption-stdout', action='store_true')
    parser.add_argument('sources', nargs='+', type=Path)
    args = parser.parse_args()
    signal.alarm(15)
    try:
        manifest, archive = capture(args.sources)
        if args.archive_to_encryption_stdout:
            sys.stdout.buffer.write(archive)
        else:
            print(json.dumps(public_summary(manifest), sort_keys=True))
        return 0
    except Exception as error:
        reason = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        print('lead_capture_failed_closed:' + reason, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
