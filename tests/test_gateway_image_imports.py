"""Reproduce the gateway COPY layout without broker code or Docker access."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]


def test_gateway_image_copy_layout_has_required_imports_and_denies_untrusted_origins(tmp_path):
    for line in (ROOT / "Dockerfile.gateway").read_text().splitlines():
        if not line.startswith("COPY "):
            continue
        *sources, destination = shlex.split(line)[1:]
        for source in sources:
            src = ROOT / source
            dest = tmp_path / destination
            if src.is_dir():
                shutil.copytree(src, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest / src.name)
    assert not (tmp_path / "bot/__init__.py").exists()
    assert not (tmp_path / "bot/broker_manager.py").exists()
    code = """
import sys
sys.path.insert(0, sys.argv[1])
import api_gateway
assert api_gateway.user_control is not None
assert api_gateway.permission_validator is not None
assert api_gateway.get_api_key_manager() is not None
assert api_gateway.get_user_manager() is not None
assert api_gateway.origins_list == ['https://trusted.example']
"""
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "JWT_SECRET_KEY": Fernet.generate_key().decode(),
        "NIJA_API_KEY_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "NIJA_ENVIRONMENT": "production",
        "ALLOWED_ORIGINS": "https://trusted.example",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run([sys.executable, "-P", "-c", code, str(tmp_path)], cwd=tmp_path,
                            env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
