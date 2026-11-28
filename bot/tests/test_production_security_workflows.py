"""Offline tests for database acquisition and release security enforcement."""
from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]


class TrivyAcquisitionTests(unittest.TestCase):
    """A missing database or failed scan must never become a green check."""

    def run_scan(self, mode: str, scan_status: int = 0) -> tuple[subprocess.CompletedProcess, list[str]]:
        """Run the real wrapper against a deterministic offline scanner stub."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scanner = root / "trivy"
            scanner.write_text(
                "#!/bin/bash\n"
                'echo "$*" >> "$CALLS"\n'
                'if [[ "$*" == *"--download-db-only"* ]]; then\n'
                '  [[ "$MODE" == "all-fail" ]] && exit 1\n'
                '  [[ "$MODE" == "fallback" && "$*" == *"mirror.gcr.io"* ]] && exit 1\n'
                "  exit 0\n"
                "fi\n"
                'exit "$SCAN_STATUS"\n',
                encoding="utf-8",
            )
            scanner.chmod(0o700)
            sleep = root / "sleep"
            sleep.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
            sleep.chmod(0o700)
            calls = root / "calls"
            env = dict(os.environ, PATH=f"{root}:{os.environ['PATH']}", CALLS=str(calls),
                       MODE=mode, SCAN_STATUS=str(scan_status))
            result = subprocess.run(
                ["bash", str(ROOT / "scripts/run_trivy_scan.sh"), "fs",
                 "--severity", "CRITICAL,HIGH", "."],
                env=env, capture_output=True, text=True, timeout=10,
            )
            return result, calls.read_text(encoding="utf-8").splitlines()

    def test_primary_database_and_enforced_scan(self) -> None:
        result, calls = self.run_scan("success")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(calls), 2)
        self.assertIn("mirror.gcr.io/aquasec/trivy-db:2", calls[0])
        self.assertIn("--skip-db-update --exit-code 1", calls[-1])

    def test_registry_failure_uses_bounded_fallback(self) -> None:
        result, calls = self.run_scan("fallback")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(calls), 5)
        self.assertIn("ghcr.io/aquasecurity/trivy-db:2", calls[-2])

    def test_database_failure_never_scans_old_cache(self) -> None:
        result, calls = self.run_scan("all-fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 9)
        self.assertTrue(all("--download-db-only" in call for call in calls))
        self.assertIn("scan denied", result.stderr)

    def test_scanner_failures_and_findings_propagate(self) -> None:
        for status in (1, 2, 42):
            with self.subTest(status=status):
                result, _ = self.run_scan("success", status)
                self.assertEqual(result.returncode, status)


class ReleaseWorkflowTests(unittest.TestCase):
    """Keep signing and all production vulnerability gates mandatory."""

    def test_scanners_do_not_suppress_failures(self) -> None:
        for name in ("artifact-scanning.yml", "zero-trust-ci.yml", "canary-deployment.yml"):
            workflow = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
            steps = [step for job in workflow["jobs"].values() for step in job.get("steps", [])]
            scans = [step for step in steps if "run_trivy_scan.sh" in step.get("run", "")]
            self.assertTrue(scans, name)
            for step in scans:
                self.assertNotIn("continue-on-error", step)
                self.assertNotIn("--exit-code 0", step["run"])
                self.assertNotIn("|| true", step["run"])

    def test_cosign_verifies_exact_workflow_identity_and_digest(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/canary-deployment.yml").read_text())
        build = workflow["jobs"]["build-and-scan"]
        self.assertEqual(build["permissions"]["id-token"], "write")
        signing = next(step for step in build["steps"] if step["name"] == "Sign container image")
        self.assertNotIn("continue-on-error", signing)
        for value in ("cosign sign --yes", "cosign verify", "github.workflow_ref",
                      "--certificate-oidc-issuer", "steps.build.outputs.digest"):
            self.assertIn(value, signing["run"])
        for job_name in ("deploy-canary", "finalize-deployment"):
            job = workflow["jobs"][job_name]
            scripts = "\n".join(step.get("run", "") for step in job["steps"])
            self.assertIn("needs.build-and-scan.outputs.image-digest", scripts)

    def test_codeql_preserves_both_languages_and_enforced_analysis(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/codeql.yml").read_text())
        job = workflow["jobs"]["analyze"]
        self.assertEqual(set(job["strategy"]["matrix"]["language"]), {"python", "javascript"})
        self.assertEqual(job["permissions"]["security-events"], "write")
        analysis = next(step for step in job["steps"] if step.get("uses", "").startswith(
            "github/codeql-action/analyze@"))
        self.assertNotIn("continue-on-error", analysis)
        self.assertIn("category", analysis["with"])

    def test_python_audits_enforce_findings(self) -> None:
        for name in ("security-scan.yml", "artifact-scanning.yml"):
            workflow = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
            executable = (
                "$RUNNER_TEMP/nija-pip-audit/bin/pip-audit"
                if name == "artifact-scanning.yml" else "pip-audit"
            )
            prefix = f'"{executable}" ' if executable.startswith("$") else f"{executable} "
            audits = [
                (step, line.strip())
                for job in workflow["jobs"].values()
                for step in job.get("steps", [])
                for line in step.get("run", "").splitlines()
                if line.strip().startswith(prefix)
            ]
            self.assertTrue(audits, name)
            for step, command in audits:
                self.assertNotIn("continue-on-error", step)
                self.assertNotIn("if", step)
                self.assertNotIn("||", step["run"])
                args = shlex.split(command)
                self.assertEqual(args[0], executable)
                self.assertIn("--desc", args)
                self.assertFalse(any(arg.startswith("--ignore-vuln") for arg in args))
                if name == "artifact-scanning.yml":
                    self.assertIn("-r", args)
                    self.assertEqual(args[args.index("-r") + 1],
                                     "${{ matrix.requirements }}")
        workflow = yaml.safe_load((ROOT / ".github/workflows/artifact-scanning.yml").read_text())
        manifests = workflow["jobs"]["python-package-scan"]["strategy"]["matrix"]["requirements"]
        self.assertEqual(set(manifests), {
            "requirements.txt", "requirements-billing.txt", "requirements-member-broker.txt",
            "requirements-notebook.txt",
        })
        guarddog = next(step for step in workflow["jobs"]["python-package-scan"]["steps"]
                        if 'nija-guarddog/bin/guarddog" pypi verify' in step.get("run", ""))
        self.assertIn(
            '"$RUNNER_TEMP/nija-guarddog/bin/guarddog" pypi verify "${{ matrix.requirements }}"',
            guarddog["run"],
        )
        self.assertIn("--exit-non-zero-on-finding", guarddog["run"])
        self.assertIn('scripts/check_guarddog_report.py guarddog-report.json "$guarddog_status"',
                      guarddog["run"])
        self.assertIn("steps.production-deps.outcome == 'success'", guarddog["if"])
        self.assertNotIn("continue-on-error", guarddog)
        self.assertNotIn("||", guarddog["run"])

    def test_redis_hardening_preserves_durable_data(self) -> None:
        documents = yaml.safe_load_all((ROOT / "k8s/components/redis/deployment.yaml").read_text())
        deployment = next(doc for doc in documents if doc["kind"] == "Deployment")
        pod = deployment["spec"]["template"]["spec"]
        self.assertTrue(pod["securityContext"]["runAsNonRoot"])
        self.assertEqual(pod["securityContext"]["fsGroup"], pod["securityContext"]["runAsGroup"])
        redis = pod["containers"][0]
        context = redis["securityContext"]
        self.assertTrue(context["readOnlyRootFilesystem"])
        self.assertFalse(context["allowPrivilegeEscalation"])
        self.assertEqual(context["capabilities"]["drop"], ["ALL"])
        self.assertIn("--appendonly", redis["args"])
        self.assertEqual(redis["volumeMounts"], [{"name": "redis-storage", "mountPath": "/data"}])
        self.assertEqual(pod["volumes"][0]["persistentVolumeClaim"]["claimName"], "redis-pvc")

    def test_postgres_hardening_preserves_writable_state_and_socket_paths(self) -> None:
        documents = yaml.safe_load_all((ROOT / "k8s/components/postgres/statefulset.yaml").read_text())
        statefulset = next(doc for doc in documents if doc["kind"] == "StatefulSet")
        pod = statefulset["spec"]["template"]["spec"]
        self.assertEqual(pod["securityContext"]["runAsUser"], 70)
        self.assertEqual(pod["securityContext"]["fsGroup"], 70)
        self.assertTrue(pod["securityContext"]["runAsNonRoot"])
        postgres = pod["containers"][0]
        self.assertTrue(postgres["securityContext"]["readOnlyRootFilesystem"])
        self.assertFalse(postgres["securityContext"]["allowPrivilegeEscalation"])
        self.assertEqual(postgres["securityContext"]["capabilities"]["drop"], ["ALL"])
        mounts = {mount["mountPath"]: mount["name"] for mount in postgres["volumeMounts"]}
        self.assertEqual(mounts["/var/lib/postgresql/data"], "postgres-storage")
        self.assertEqual(mounts["/var/run/postgresql"], "postgres-run")
        self.assertEqual(mounts["/tmp"], "postgres-tmp")
        volumes = {volume["name"]: volume for volume in pod["volumes"]}
        self.assertEqual(volumes["postgres-run"]["emptyDir"], {})
        self.assertEqual(volumes["postgres-tmp"]["emptyDir"], {})
        self.assertEqual(statefulset["spec"]["volumeClaimTemplates"][0]["metadata"]["name"],
                         "postgres-storage")

    def test_dashboard_hardening_runs_non_root_with_writable_runtime_storage(self) -> None:
        documents = yaml.safe_load_all((ROOT / "k8s/components/dashboard/deployment.yaml").read_text())
        deployment = next(doc for doc in documents if doc["kind"] == "Deployment")
        pod = deployment["spec"]["template"]["spec"]
        self.assertTrue(pod["securityContext"]["runAsNonRoot"])
        self.assertEqual(pod["securityContext"]["runAsUser"], 10001)
        self.assertEqual(pod["securityContext"]["fsGroup"], 10001)
        self.assertEqual(pod["securityContext"]["seccompProfile"]["type"], "RuntimeDefault")
        dashboard = pod["containers"][0]
        self.assertTrue(dashboard["securityContext"]["readOnlyRootFilesystem"])
        self.assertFalse(dashboard["securityContext"]["allowPrivilegeEscalation"])
        self.assertEqual(dashboard["securityContext"]["capabilities"]["drop"], ["ALL"])
        mounts = {mount["mountPath"]: mount["name"] for mount in dashboard["volumeMounts"]}
        self.assertEqual(mounts, {"/tmp": "dashboard-tmp", "/app/logs": "dashboard-logs"})
        volumes = {volume["name"]: volume["emptyDir"] for volume in pod["volumes"]}
        self.assertEqual(volumes, {"dashboard-tmp": {}, "dashboard-logs": {}})

    def test_api_hardening_matches_non_root_image_user_and_ephemeral_temp_storage(self) -> None:
        documents = yaml.safe_load_all((ROOT / "k8s/components/api/deployment.yaml").read_text())
        deployment = next(doc for doc in documents if doc["kind"] == "Deployment")
        pod = deployment["spec"]["template"]["spec"]
        self.assertIn("useradd -m -u 1000 nija", (ROOT / "Dockerfile.api").read_text())
        self.assertTrue(pod["securityContext"]["runAsNonRoot"])
        self.assertEqual(pod["securityContext"]["runAsUser"], 1000)
        self.assertEqual(pod["securityContext"]["seccompProfile"]["type"], "RuntimeDefault")
        api = pod["containers"][0]
        self.assertTrue(api["securityContext"]["readOnlyRootFilesystem"])
        self.assertFalse(api["securityContext"]["allowPrivilegeEscalation"])
        self.assertTrue(api["securityContext"]["runAsNonRoot"])
        self.assertEqual(api["securityContext"]["runAsUser"], 1000)
        self.assertEqual(api["securityContext"]["capabilities"]["drop"], ["ALL"])
        self.assertIn({"name": "PYTHONDONTWRITEBYTECODE", "value": "1"}, api["env"])
        self.assertEqual(api["volumeMounts"], [{"name": "api-tmp", "mountPath": "/tmp"}])
        self.assertEqual(pod["volumes"], [{"name": "api-tmp", "emptyDir": {}}])

    def test_dashboard_images_use_non_root_users_and_required_writable_paths(self) -> None:
        for dockerfile in ("Dockerfile", "Dockerfile.api", "Dockerfile.dashboard", "Dockerfile.gateway"):
            self.assertIn("--no-install-recommends", (ROOT / dockerfile).read_text())
        dashboard = (ROOT / "Dockerfile.dashboard").read_text()
        self.assertIn("USER dashboard", dashboard)
        self.assertIn("chown dashboard:dashboard /app/logs", dashboard)
        realtime = (ROOT / "Dockerfile.realtime-dashboard").read_text()
        self.assertIn("USER dashboard", realtime)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", realtime)

    def test_image_findings_do_not_skip_independent_scanner_or_evidence(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/artifact-scanning.yml").read_text())
        steps = workflow["jobs"]["docker-image-scan"]["steps"]
        build = next(step for step in steps if step.get("id") == "build-image")
        binding = next(step for step in steps if step.get("id") == "scan-target")
        grype = next(step for step in steps if step.get("id") == "grype-scan")
        trivy = [step for step in steps if "run_trivy_scan.sh image" in step.get("run", "")]
        self.assertEqual(len(trivy), 2)
        self.assertLess(steps.index(build), steps.index(binding))
        self.assertLess(steps.index(binding), min(map(steps.index, [*trivy, grype])))
        self.assertNotIn("continue-on-error", binding)
        for step in trivy:
            self.assertIn("--image-src docker", step["run"])
            self.assertIn("steps.scan-target.outputs.id", step["run"])
        self.assertIn("steps.scan-target.outcome == 'success'", trivy[1]["if"])
        self.assertIn("!cancelled()", trivy[1]["if"])
        self.assertIn("steps.scan-target.outcome == 'success'", grype["if"])
        self.assertIn("!cancelled()", grype["if"])
        self.assertEqual(grype["with"]["image"], "docker:${{ steps.scan-target.outputs.id }}")
        self.assertTrue(grype["with"]["fail-build"])
        self.assertEqual(grype["with"]["severity-cutoff"], "high")
        evidence = next(step for step in steps if step["name"] == "Retain raw container scan evidence")
        self.assertIn("always()", evidence["if"])
        self.assertIn("steps.scan-target.outcome == 'success'", evidence["if"])
        self.assertIn("container-scan-target.txt", evidence["with"]["path"])
        self.assertIn("trivy-results-", evidence["with"]["path"])
        self.assertIn("steps.grype-scan.outputs.sarif", evidence["with"]["path"])

    def test_scan_binding_accepts_both_exact_docker_ids_and_rejects_drift(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/artifact-scanning.yml").read_text())
        steps = workflow["jobs"]["docker-image-scan"]["steps"]
        binding = next(step for step in steps if step.get("id") == "scan-target")["run"]
        config = "sha256:" + "1" * 64
        target = "sha256:" + "2" * 64
        foreign = "sha256:" + "3" * 64
        cases = [
            (config, config, target, "", "config"),
            (target, config, target, "", "export_target"),
            (target, "", "", f"#19 exporting config {config} done\n#19 exporting manifest {target} done\n",
             "export_target"),
            (foreign, config, target, "", None),
            (target, "invalid", target, "", None),
            (target, config, "", "", None),
            (target, config, "", f"#19 exporting manifest {target} done\n#20 exporting manifest {foreign} done\n",
             None),
        ]
        for image, built_config, built_target, log, expected in cases:
            with self.subTest(expected=expected, image=image, target=built_target), tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                docker = tmp / "docker"
                docker.write_text('#!/bin/sh\nprintf "%s\\n" "$TEST_DOCKER_ID"\n', encoding="utf-8")
                docker.chmod(0o700)
                git = tmp / "git"
                git.write_text("#!/bin/sh\nprintf '%040d\\n' 1\n", encoding="utf-8")
                git.chmod(0o700)
                (tmp / "nija-container-build.json").write_text(json.dumps({
                    "containerimage.config.digest": built_config,
                    "containerimage.digest": built_target,
                }), encoding="utf-8")
                (tmp / "nija-container-build.log").write_text(log, encoding="utf-8")
                output = tmp / "outputs"
                result = subprocess.run(
                    ["bash", "-c", binding], cwd=tmp, capture_output=True, text=True,
                    env={**os.environ, "PATH": str(tmp) + os.pathsep + os.defpath,
                         "TEST_DOCKER_ID": image, "RUNNER_TEMP": str(tmp), "GITHUB_OUTPUT": str(output),
                         "IMAGE": "fixture:latest", "DOCKERFILE": "Dockerfile"},
                    timeout=5,
                )
                receipt = tmp / "container-scan-target.txt"
                if expected is None:
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertFalse(output.exists())
                    self.assertFalse(receipt.exists())
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(output.read_text(), f"id={image}\n")
                    self.assertIn(f"local_image_id_kind={expected}\n", receipt.read_text())
                    self.assertIn(f"build_config_digest={config}\n", receipt.read_text())
                    self.assertIn(f"build_manifest_digest={target}\n", receipt.read_text())


if __name__ == "__main__":
    unittest.main()
