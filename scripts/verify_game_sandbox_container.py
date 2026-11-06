#!/usr/bin/env python3
"""Rehearse rootless startup with disposable Docker resources and no credentials."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
import uuid


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Bound every Docker operation; never print container environment or logs."""
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True, timeout=30)


def verify(image: str) -> None:
    """Verify real UID, denied root, mount requirements, persistence and HTTP hold."""
    identity = docker("image", "inspect", image, "--format", "{{.Config.User}}").stdout.strip()
    if identity != "10001:10001":
        raise RuntimeError("non_root_image_identity_required")
    denied = docker("run", "--rm", "--network", "none", "--user", "0", image, check=False)
    if denied.returncode == 0 or "Sandbox startup denied" not in denied.stderr:
        raise RuntimeError("root_override_was_not_denied")

    settings = ["-e", "NIJA_IQ_SANDBOX_ENABLED=true", "-e",
                "NIJA_IQ_SANDBOX_DATABASE=/var/data/trading_iq_sandbox.sqlite3"]
    python = "/opt/venv/bin/python"
    missing = docker("run", "--rm", "--network", "none", *settings,
                     "--entrypoint", python, image, "-c",
                     "from game_sandbox.staging_bootstrap import validate_runtime; validate_runtime()",
                     check=False)
    if missing.returncode == 0 or "sandbox_persistent_mount_required" not in missing.stderr:
        raise RuntimeError("missing_mount_was_not_denied")

    volume = "nija-iq-security-test-" + uuid.uuid4().hex
    container = None
    docker("volume", "create", volume)
    try:
        mounted = ["--mount", "type=volume,src=" + volume + ",dst=/var/data,volume-nocopy"]
        # Model an unprovisioned mount explicitly; Docker's initial volume
        # copy-up can otherwise inherit the image directory's correct owner.
        docker("run", "--rm", "--network", "none", "--user", "0", *mounted,
               "--entrypoint", python, image, "-c",
               "import os; os.chown('/var/data',0,0); os.chmod('/var/data',0o755)")
        owner = docker("run", "--rm", "--network", "none", *settings, *mounted,
                       "--entrypoint", python, image, "-c",
                       "from game_sandbox.staging_bootstrap import validate_runtime; validate_runtime()",
                       check=False)
        if owner.returncode == 0 or "sandbox_private_disk_owner_required" not in owner.stderr:
            categories = ("sandbox_non_root_user_required", "sandbox_persistent_mount_required",
                          "sandbox_private_disk_owner_required", "PermissionError", "ModuleNotFoundError")
            category = next((value for value in categories if value in owner.stderr), "unexpected_result")
            raise RuntimeError(f"unprovisioned_mount_check_failed: exit={owner.returncode}, category={category}")
        # Provision only this newly created, disposable CI volume. This is never
        # a service-startup path and has no provider credentials or customer data.
        docker("run", "--rm", "--network", "none", "--user", "0", *mounted,
               "--entrypoint", python, image, "-c",
               "import os; os.chown('/var/data',10001,10001); os.chmod('/var/data',0o700)")
        probe = (
            "import os,sqlite3; from game_sandbox.staging_bootstrap import validate_runtime; "
            "assert os.geteuid()==10001; validate_runtime(); "
            "c=sqlite3.connect('/var/data/trading_iq_sandbox.sqlite3'); "
        )
        docker("run", "--rm", "--network", "none", *settings, *mounted,
               "--entrypoint", python, image, "-c", probe +
               "c.execute('CREATE TABLE rehearsal(value INTEGER)'); "
               "c.execute('INSERT INTO rehearsal VALUES (7)'); c.commit(); c.close()")
        # A second process must read the original volume's record after restart.
        docker("run", "--rm", "--network", "none", *settings, *mounted,
               "--entrypoint", python, image, "-c", probe +
               "assert c.execute('SELECT value FROM rehearsal').fetchone()==(7,); c.close()")
        readonly = docker("run", "--rm", "--network", "none", *settings,
                          "--mount", "type=volume,src=" + volume + ",dst=/var/data,readonly,volume-nocopy", "--entrypoint", python,
                          image, "-c", "from game_sandbox.staging_bootstrap import validate_runtime; validate_runtime()",
                          check=False)
        if readonly.returncode == 0:
            raise RuntimeError("read_only_storage_was_not_denied")
        container = docker(
            "run", "-d", "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=16m",
            "-e", "NIJA_IQ_SANDBOX_ENABLED=false", image,
        ).stdout.strip()
        query = (
            "import json,urllib.request; "
            "print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:10000/healthz',timeout=2))))"
        )
        for _ in range(20):
            result = docker("exec", container, python, "-c", query, check=False)
            if result.returncode == 0:
                health = json.loads(result.stdout)
                if (health.get("checkout_available") is not False or health.get("live_payments") is not False
                        or health.get("status") != "staging_holding"):
                    raise RuntimeError("disabled_health_contract_failed")
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("disabled_server_did_not_start")
        docker("exec", container, python, "-c",
               "import urllib.request,urllib.error; "
               "r=urllib.request.Request('http://127.0.0.1:10000/sandbox/runs',data=b'{}'); "
               "\ntry: urllib.request.urlopen(r,timeout=2); raise SystemExit(1)"
               "\nexcept urllib.error.HTTPError as e: assert e.code==503")
        docker("exec", container, "node", "--version")
    finally:
        if container:
            docker("rm", "--force", container, check=False)
        docker("volume", "rm", "--force", volume, check=False)


def main() -> None:
    """Run the rehearsal without deploying or accessing Stripe or any broker."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    verify(parser.parse_args().image)
    print("Rootless sandbox container and disabled HTTP checks passed.")


if __name__ == "__main__":
    main()
