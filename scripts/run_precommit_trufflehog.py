"""Enforce the existing verified-secret scan without printing candidate values."""
from __future__ import annotations

import json
import shutil
import subprocess


def main() -> int:
    """Keep scanner errors and findings blocking; print fixed summaries only."""
    try:
        executable = shutil.which("trufflehog")
        if executable is None:
            raise FileNotFoundError("scanner_unavailable")
        result = subprocess.run(
            [executable, "filesystem", ".", "--only-verified", "--json", "--fail"],
            capture_output=True, text=True, timeout=900, check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        print("TruffleHog: scanner unavailable or timed out; scan denied.")
        return 2
    if result.returncode != 0:
        print("TruffleHog: verified findings or scanner failure; scan denied.")
        return result.returncode if 0 < result.returncode <= 255 else 2
    # --only-verified emits candidate results on stdout, not informational logs.
    # A scanner returning success alongside results must still block the hook.
    try:
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    except (ValueError, TypeError):
        print("TruffleHog: invalid scanner result; scan denied.")
        return 2
    if rows:
        print("TruffleHog: unexpected candidate output; scan denied.")
        return 183
    print("TruffleHog: verified-secret scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
