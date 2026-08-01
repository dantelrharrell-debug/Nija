from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "credential_diagnostics.sh"


def _run(extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KRAKEN_USER_TANIA")
    }
    env.update(extra_env)
    return subprocess.run(
        [
            "bash",
            "-c",
            f'source "{HELPER}"; '
            'nija_print_kraken_user_credential_status "User #2: Tania" "TANIA" "TANIA_GILBERT"',
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_full_name_tania_credentials_are_detected() -> None:
    result = _run(
        {
            "KRAKEN_USER_TANIA_GILBERT_API_KEY": "full-key",
            "KRAKEN_USER_TANIA_GILBERT_API_SECRET": "full-secret",
        }
    )

    assert result.returncode == 0
    assert "✅ Configured" in result.stdout
    assert "KRAKEN_USER_TANIA_GILBERT_API_KEY" in result.stdout
    assert "full-key" not in result.stdout
    assert "full-secret" not in result.stdout


def test_mixed_short_and_full_aliases_match_broker_resolution() -> None:
    result = _run(
        {
            "KRAKEN_USER_TANIA_API_KEY": "short-key",
            "KRAKEN_USER_TANIA_GILBERT_API_SECRET": "full-secret",
        }
    )

    assert result.returncode == 0
    assert "KRAKEN_USER_TANIA_API_KEY" in result.stdout
    assert "KRAKEN_USER_TANIA_GILBERT_API_SECRET" in result.stdout


def test_partial_tania_credentials_are_reported_as_incomplete() -> None:
    result = _run({"KRAKEN_USER_TANIA_GILBERT_API_KEY": "full-key"})

    assert result.returncode == 0
    assert "Incomplete configuration" in result.stdout
    assert "Secret: missing" in result.stdout
