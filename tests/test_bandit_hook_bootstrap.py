"""Exercise the real pinned hook in an isolated repository with synthetic code."""
from pathlib import Path
import os
import shutil
import subprocess  # nosec B404 # Run only fixed Git and pinned scanner commands in the test repository.
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_real_bandit_hook_bootstraps_and_still_denies_unsafe_code(tmp_path):
    """Catch missing dependencies, obsolete rule IDs and false-success repairs."""
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    repository = next(row for row in config["repos"]
                      if row["repo"] == "https://github.com/PyCQA/bandit")
    hook = next(row for row in repository["hooks"] if row["id"] == "bandit")
    isolated = {"repos": [{"repo": repository["repo"], "rev": repository["rev"],
                           "hooks": [hook]}]}
    (tmp_path / ".pre-commit-config.yaml").write_text(yaml.safe_dump(isolated))
    (tmp_path / ".bandit.yml").write_bytes((ROOT / ".bandit.yml").read_bytes())
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "init", "--quiet"], cwd=tmp_path, check=True)  # nosec B603 # Fixed argument list, no shell.
    environment = dict(os.environ, NIJA_DEFER_RUNTIME_SITE_HOOKS="1")
    environment["PRE_COMMIT_HOME"] = str(tmp_path / "hook-cache")
    probe = tmp_path / "probe.py"
    command = [sys.executable, "-m", "pre_commit", "run", "bandit", "--files", "probe.py"]

    probe.write_text('"""Safe synthetic code; never imports the application."""\nvalue = 1\n')
    clean = subprocess.run(command, cwd=tmp_path, env=environment,  # nosec B603 # Fixed interpreter and hook arguments.
                           capture_output=True, text=True, timeout=180)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    assert "Passed" in clean.stdout

    # Bandit analyzes this fixture as text; it is never imported or executed.
    probe.write_text("import pickle\npickle.loads(payload)\n")
    unsafe = subprocess.run(command, cwd=tmp_path, env=environment,  # nosec B603 # Same fixed scanner command.
                            capture_output=True, text=True, timeout=60)
    assert unsafe.returncode == 1, unsafe.stdout + unsafe.stderr
    assert "B301" in unsafe.stdout
    assert "ModuleNotFoundError" not in unsafe.stdout + unsafe.stderr
    assert "Unknown test" not in unsafe.stdout + unsafe.stderr
