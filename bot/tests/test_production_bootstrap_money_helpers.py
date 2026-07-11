from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_money_helpers_use_isolated_python_startup() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "scripts" / "production_bootstrap.sh").read_text(encoding="utf-8")

    assert '_is_positive_money()' in source
    assert '_max_money()' in source
    assert 'python3 -S - "$1"' in source
    assert 'python3 -S - "$@"' in source
    assert 'value.is_finite()' in source
    assert 'any(not value.is_finite() for value in values)' in source


def test_isolated_money_command_substitution_returns_only_number(tmp_path: Path) -> None:
    """A noisy sitecustomize must not contaminate the captured money value."""

    (tmp_path / "sitecustomize.py").write_text(
        'print("SHOULD_NOT_APPEAR_IN_MONEY_OUTPUT", flush=True)\n',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path)

    script = r'''
set -euo pipefail
value="$(python3 -S - "23.10" "10.00" <<'PY'
from decimal import Decimal
import sys
values = [Decimal(item) for item in sys.argv[1:]]
print(f"{max(values):.2f}")
PY
)"
[[ "${value}" == "23.10" ]]
printf '%s\n' "${value}"
'''
    completed = subprocess.run(
        ["bash", "-c", script],
        cwd=str(tmp_path),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stdout
    assert completed.stdout.strip() == "23.10"
    assert "SHOULD_NOT_APPEAR" not in completed.stdout


def test_three_venue_verifier_is_included_in_docker_context() -> None:
    root = Path(__file__).resolve().parents[2]
    rules = (root / ".dockerignore").read_text(encoding="utf-8").splitlines()

    exclude_index = rules.index("scripts/*")
    include_index = rules.index("!scripts/three_venue_config_check.py")
    assert include_index > exclude_index


def test_docker_image_validates_committed_three_venue_bootstrap() -> None:
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")

    assert "test -f /app/scripts/three_venue_config_check.py" in dockerfile
    assert "/app/scripts/three_venue_config_check.py" in dockerfile
    assert "bash -n /app/scripts/production_bootstrap.sh" in dockerfile
    assert "unexpected three-venue bootstrap block" not in dockerfile
    assert "p.write_text(s.replace" not in dockerfile
