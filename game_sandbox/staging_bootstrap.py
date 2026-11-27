"""Start only the isolated educational sandbox under an unprivileged identity."""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import sys
import tempfile


def has_dedicated_mount(data_directory: Path) -> bool:
    """Read Linux's mount table; stat-based ismount misses same-device bind mounts."""
    with Path("/proc/self/mountinfo").open(encoding="utf-8") as source:
        mountinfo = source.read(1024 * 1024 + 1)
    if len(mountinfo) > 1024 * 1024:
        raise RuntimeError("sandbox_mount_table_limit_exceeded")
    return mount_table_contains(data_directory, mountinfo)


def mount_table_contains(data_directory: Path, mountinfo: str) -> bool:
    """Match the exact fifth mountinfo field, decoding kernel octal path escapes."""
    for line in mountinfo.splitlines():
        fields = line.split()
        if len(fields) < 10 or "-" not in fields[6:]:
            continue
        mountpoint = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), fields[4])
        if mountpoint == str(data_directory):
            return True
    return False


def validate_runtime(data_directory: Path = Path("/var/data")) -> None:
    """Require non-root execution and private writable storage before enablement."""
    uid = os.geteuid()
    if uid == 0:
        raise RuntimeError("sandbox_non_root_user_required")
    if os.environ.get("NIJA_IQ_SANDBOX_ENABLED") != "true":
        return
    database = Path(os.environ.get("NIJA_IQ_SANDBOX_DATABASE", ""))
    # Never fall back to a disposable directory if the dedicated mount is absent.
    if database != data_directory / "trading_iq_sandbox.sqlite3":
        raise RuntimeError("sandbox_dedicated_disk_path_required")
    if not has_dedicated_mount(data_directory):
        raise RuntimeError("sandbox_persistent_mount_required")
    metadata = data_directory.lstat()
    if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != uid
            or stat.S_IMODE(metadata.st_mode) & 0o077):
        raise RuntimeError("sandbox_private_disk_owner_required")
    # Exercise an actual write under the runtime identity; access() alone can
    # claim success on some read-only mounts. No entitlement record is touched.
    with tempfile.TemporaryFile(dir=data_directory) as probe:
        probe.write(b"sandbox-storage-probe")
        probe.flush()
        os.fsync(probe.fileno())


def main() -> int:
    """Validate storage, then replace this process so Gunicorn receives signals."""
    try:
        validate_runtime()
    except (OSError, RuntimeError):
        # No environment values, paths, database contents or credentials in logs.
        print("Sandbox startup denied: non-root identity/private disk preflight failed.", file=sys.stderr)
        return 1
    # Fixed interpreter/module, argv only; PORT is one bind argument, never shell text.
    os.execv(sys.executable, [  # nosec B606
        sys.executable, "-m", "gunicorn", "game_sandbox.staging_entrypoint:application",
        "--bind", f"0.0.0.0:{os.environ.get('PORT', '10000')}",
        "--workers", "1", "--threads", "2", "--error-logfile", "-",
    ])
    return 1  # execv either replaces this process or raises; never continue serving.


if __name__ == "__main__":
    raise SystemExit(main())
