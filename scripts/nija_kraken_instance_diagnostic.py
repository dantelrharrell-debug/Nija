"""Bounded stdin-only Render inspection; no imports of NIJA or broker clients.

Run with python -B -S on the authorized service. Only fixed diagnostic labels,
credential-presence booleans and public source/deployment digests leave it.
The explicit identity-request mode publishes one immutable diagnostic request
for the existing broker; default inspection and result reads never write state.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SERVICE = "srv-d98dsr5aeets73fpbaqg"
BASELINE = "cd174134ff4a61824322cecc042d1548bd938a34"
MAX_BYTES = 4 * 1024 * 1024
IDENTITY_REQUEST = hashlib.sha256((SERVICE + BASELINE + "20261102identity").encode()).hexdigest()[:32]
RECOVERY_ROOT = Path("/data/kraken-history-recovery")
APP_ROOT = Path("/app")
SIGNALS = {
    "INVALID_API_KEY": (
        "eapi:invalid key",
        "reason=invalid_api_key",
    ),
    "INVALID_SIGNATURE": ("eapi:invalid signature", "reason=invalid_signature"),
    "NONCE_REJECTED": ("eapi:invalid nonce", "reason=nonce_rejected"),
    "PERMISSION_DENIED": ("egeneral:permission denied", "eapi:invalid permission"),
    "ACCOUNT_DISABLED": ("eaccount:account disabled",),
    "TEMPORARY_LOCKOUT": ("eapi:temporary lockout",),
    "CREDENTIAL_PAIR_MISSING_OR_INCOMPLETE": ("credential_pair_missing_or_incomplete",),
    "INVALID_SECRET_ENCODING": ("invalid_secret_encoding",),
    "WRITER_AUTHORITY_UNAVAILABLE": (
        "kraken_nonce_startup_blocked", "canonical process writer authority unavailable",
    ),
    "NONCE_LEASE_UNAVAILABLE": ("nonce authority unavailable",),
    "DNS_FAILURE": ("nameresolutionerror", "name or service not known"),
    "TLS_FAILURE": ("sslerror", "certificate_verify_failed"),
    "TRANSPORT_TIMEOUT": ("readtimeout", "connecttimeout"),
    "TRANSPORT_DISCONNECTED": ("remotedisconnected", "connection aborted"),
    "COLLECTOR_MISSING": ("collector_installed=false", "producer_status=collector_missing"),
    "PRICE_CLIENT_DISCONNECTED": ("kraken api not connected",),
    "PRICE_CLIENT_PLATFORM_DISCONNECTED": ("kraken_market_data_unavailable account_role=platform",),
    "PRICE_CLIENT_CUSTOMER_DISCONNECTED": ("kraken_market_data_unavailable account_role=customer",),
    "AUTHENTICATED_BALANCE_FAILED": ("kraken connection test failed",),
    "AUTHENTICATED_CONNECTION_SUCCEEDED": ("successfully connected to kraken",),
    "RECOVERY_WAITING_FOR_WRITER": ("kraken_authenticated_recovery_waiting",),
    "RECOVERY_PERMANENT_FAILURE": ("kraken_authenticated_recovery_perm_failure",),
    "CONNECTION_INITIALIZATION_FAILED": ("connection_initialization_failed",),
    "INITIALIZATION_BLOCKED": ("kraken_initialization_blocked",),
    "CLOCK_NOT_READY": ("kraken_clock_not_ready",),
    "PLATFORM_CREDENTIALS_MISSING": ("credentials not configured for platform",),
    "CUSTOMER_CREDENTIALS_MISSING": ("credentials not configured for user:",),
    "MISSING_CANONICAL_NAMESPACE": ("kraken_credential_pair_required key_variable=kraken_platform_api_key",),
    "MISSING_LEGACY_NAMESPACE": ("kraken_credential_pair_required key_variable=kraken_api_key",),
    "MISSING_CUSTOMER_NAMESPACE": ("kraken_credential_pair_required key_variable=kraken_user_",),
    "CLOCK_GATE_BLOCKED": ("kraken_clock_gate_blocked",),
    "CLOCK_GATE_VERIFIED": ("kraken_clock_gate_verified",),
    "AUTHENTICATED_RECOVERY_ATTEMPTED": ("kraken_authenticated_recovery_attempt",),
    "AUTHENTICATED_RECOVERY_SUCCEEDED": ("kraken_authenticated_recovery_ready",),
    "PLATFORM_AUTHENTICATED_BALANCE_SUCCEEDED": ("platform kraken connected",),
}
STAMP = re.compile(r"(\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d)")


def classify_log(text: str, *, since: float) -> dict[str, int]:
    """Count only recognized labels on timestamped current-process log lines."""
    counts: Counter[str] = Counter()
    for line in text.splitlines():
        match = STAMP.search(line)
        if match is None:
            continue
        try:
            stamp = datetime.fromisoformat(match[1]).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
        if stamp < since:
            continue
        lowered = line.lower()
        for label, fragments in SIGNALS.items():
            if any(fragment in lowered for fragment in fragments):
                counts[label] += 1
    return dict(counts)


def _read_regular(path: Path, limit: int, *, tail: bool = False) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("regular_file_required")
        if tail:
            os.lseek(fd, max(0, info.st_size - limit), os.SEEK_SET)
        elif info.st_size > limit:
            raise ValueError("file_budget_exceeded")
        return os.read(fd, limit)
    finally:
        os.close(fd)


def inspect_instance() -> dict:
    """Inspect the exact baseline instance without touching runtime authority."""
    if os.environ.get("RENDER_SERVICE_ID") != SERVICE:
        return {"status": "BLOCKED", "reason": "service_identity_mismatch"}
    commit = os.environ.get("RENDER_GIT_COMMIT", "")
    if commit != BASELINE:
        return {"status": "BLOCKED", "reason": "baseline_commit_mismatch"}
    result = {
        "status": "DIAGNOSTIC_ONLY", "service_id": SERVICE, "commit": commit,
        "observed_at_epoch": time.time(), "broker_requests": False,
        "state_changed": False, "allow_new_orders": False,
        "processes": [], "log_signals": {}, "source_sha256": {}, "failures": [],
    }
    instance = os.environ.get("RENDER_INSTANCE_ID", "")
    if re.fullmatch(r"[a-zA-Z0-9-]{1,100}", instance):
        result["instance_id"] = instance
    try:
        uptime = float(Path("/proc/uptime").read_text().split()[0])
        boot = time.time() - uptime
        ticks = os.sysconf("SC_CLK_TCK")
        for process in Path("/proc").iterdir():
            if not process.name.isdigit() or int(process.name) == os.getpid():
                continue
            try:
                args = (process / "cmdline").read_bytes().split(b"\0")
                if not any(arg.rsplit(b"/", 1)[-1] in {
                    b"main.py", b"bot.py", b"bot.bot_main",
                    b"canonical_runtime_launcher_v26.py",
                } for arg in args):
                    continue
                fields = (process / "stat").read_text().rsplit(")", 1)[1].split()
                started = boot + int(fields[19]) / ticks
                environment = dict(
                    item.split(b"=", 1) for item in (process / "environ").read_bytes().split(b"\0")
                    if b"=" in item
                )
                presence = {
                    name: bool(environment.get(name.encode(), b"").strip())
                    for name in (
                        "KRAKEN_PLATFORM_API_KEY", "KRAKEN_PLATFORM_API_SECRET",
                        "KRAKEN_API_KEY", "KRAKEN_API_SECRET", "REDIS_URL", "NIJA_REDIS_URL",
                    )
                }
                result["processes"].append({"started_at_epoch": started, "configured": presence})
            except (OSError, ValueError, IndexError):
                result["failures"].append("runtime_process_inspection_failed")
    except (OSError, ValueError):
        result["failures"].append("process_inventory_unavailable")
    if result["processes"]:
        since = min(row["started_at_epoch"] for row in result["processes"]) - 1
        counts: Counter[str] = Counter()
        for relative in ("nija.log", "nija.log.1", "data/nija.log", "logs/nija.log"):
            path = Path("/app") / relative
            try:
                text = _read_regular(path, MAX_BYTES, tail=True).decode("utf-8", errors="replace")
                counts.update(classify_log(text, since=since))
            except FileNotFoundError:
                continue
            except (OSError, ValueError):
                result["failures"].append("runtime_log_read_failed")
        result["log_signals"] = dict(counts)
        if not counts:
            result["failures"].append("current_process_log_evidence_unavailable")
    else:
        result["failures"].append("canonical_runtime_process_not_found")
    for relative in (
        "bot/broker_manager.py", "bot/canonical_broker_startup_convergence_v24.py",
        "scripts/render_entrypoint.sh", "scripts/production_bootstrap.sh", "start.sh",
    ):
        try:
            result["source_sha256"][relative] = hashlib.sha256(
                _read_regular(Path("/app") / relative, MAX_BYTES)
            ).hexdigest()
        except (OSError, ValueError):
            result["failures"].append("runtime_source_read_failed")
    return result


def inspect_render_api() -> dict:
    """Fetch sanitized live-deploy metadata and exact-instance logs from Render."""
    result = {
        "status": "BLOCKED", "broker_requests": False, "allow_new_orders": False,
        "failures": [], "log_signals": {},
    }
    token = os.environ.get("RENDER_API_KEY", "")
    instance = os.environ.get("EXPECTED_RENDER_INSTANCE", "")
    if not token:
        result["failures"].append("render_api_credential_unavailable")
        return result
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,100}", instance):
        result["failures"].append("current_instance_identity_unavailable")
        return result

    def get(path: str) -> object:
        request = Request("https://api.render.com/v1/" + path, headers={
            "Authorization": "Bearer " + token, "Accept": "application/json",
        })
        with urlopen(request, timeout=20) as response:
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("render_response_budget_exceeded")
            return json.loads(data)

    try:
        service = get("services/" + SERVICE)
        if not isinstance(service, dict) or service.get("id") != SERVICE:
            raise ValueError("render_service_response_invalid")
        owner = service.get("ownerId")
        if not isinstance(owner, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,100}", owner):
            raise ValueError("render_owner_identity_unavailable")
        deployments = get("services/" + SERVICE + "/deploys?limit=5")
        if not isinstance(deployments, list):
            raise ValueError("render_deploy_response_invalid")
        live = [
            row["deploy"] for row in deployments
            if isinstance(row, dict) and isinstance(row.get("deploy"), dict)
            and row["deploy"].get("status") == "live"
            and isinstance(row["deploy"].get("commit"), dict)
            and row["deploy"]["commit"].get("id") == BASELINE
        ]
        if len(live) != 1 or not re.fullmatch(r"dep-[a-zA-Z0-9]+", live[0].get("id", "")):
            raise ValueError("expected_live_deployment_unverified")
        result["deployment_id"] = live[0]["id"]
        result["commit"] = BASELINE
        result["deployment_status"] = "live"
        counts: Counter[str] = Counter()
        seen: set[str] = set()
        observed_instances: set[str] = set()
        result["log_rows_returned"] = 0
        # Fixed searches bound response size and avoid unrelated customer logs.
        for text in (
            "KRAKEN_INITIALIZATION", "KRAKEN_NONCE_STARTUP", "PRETRADE_INDEPENDENT",
            "KRAKEN_CREDENTIAL_PAIR_REQUIRED", "credentials not configured for",
            "KRAKEN_CLOCK_GATE", "KRAKEN_AUTHENTICATED_RECOVERY", "PLATFORM KRAKEN CONNECTED",
            "Price fetch failed",
        ):
            query = urlencode({
                "ownerId": owner, "resource": SERVICE,
                "text": text, "limit": 100, "direction": "backward",
                "startTime": live[0]["createdAt"],
            })
            response = get("logs?" + query)
            if not isinstance(response, dict) or not isinstance(response.get("logs"), list):
                raise ValueError("render_log_response_invalid")
            result["log_rows_returned"] += len(response["logs"])
            for row in response["logs"]:
                if not isinstance(row, dict):
                    raise ValueError("render_log_response_invalid")
                message, stamp = row.get("message"), row.get("timestamp")
                if not isinstance(message, str) or not isinstance(stamp, str):
                    raise ValueError("render_log_response_invalid")
                labels = row.get("labels")
                if not isinstance(labels, list):
                    raise ValueError("render_log_instance_unverified")
                identifiers = [
                    label.get("value") for label in labels
                    if isinstance(label, dict) and label.get("name") == "instance"
                ]
                # The API's observed label omits the Kubernetes ReplicaSet
                # component present in RENDER_INSTANCE_ID.
                if len(identifiers) != 1 or not isinstance(identifiers[0], str):
                    continue
                observed_instance = identifiers[0]
                if re.fullmatch(r"[a-zA-Z0-9-]{5,100}", observed_instance):
                    observed_instances.add(observed_instance)
                if observed_instance not in {instance, SERVICE + "-" + instance.rsplit("-", 1)[-1]}:
                    continue
                identity = hashlib.sha256((stamp + "\0" + message).encode()).hexdigest()
                if identity in seen:
                    continue
                seen.add(identity)
                counts.update(classify_log(stamp + " " + message, since=0))
        result["log_signals"] = dict(counts)
        result["observed_log_instances"] = sorted(observed_instances)
        result["status"] = "DIAGNOSTIC_ONLY"
        if not counts:
            result["failures"].append("current_instance_api_log_evidence_unavailable")
    except HTTPError as exc:
        result["failures"].append("render_api_http_" + str(exc.code))
        if exc.code == 400:
            detail = exc.read(4096).decode("utf-8", errors="replace").lower()
            for parameter in ("ownerid", "resource", "instance", "text", "starttime", "limit", "direction"):
                if parameter in detail:
                    result["failures"].append("render_api_rejected_parameter_" + parameter)
    except (OSError, URLError):
        result["failures"].append("render_api_transport_failed")
    except (KeyError, TypeError, ValueError):
        result["failures"].append("render_api_response_unverified")
    return result


def identity_probe(*, publish: bool = False) -> dict:
    """Request once or read the existing consumer's sanitized identity receipt.

    Never construct a broker, import runtime hooks, acquire writer authority,
    generate a nonce, change bindings, replay a consumed request or enable orders.
    """
    result = {
        "status": "BLOCKED", "request_id": IDENTITY_REQUEST,
        "allow_new_orders": False, "independent_certification_complete": False,
        "request_created": False,
    }
    if (os.environ.get("RENDER_SERVICE_ID") != SERVICE
            or os.environ.get("RENDER_GIT_COMMIT") != BASELINE):
        return {**result, "reason": "baseline_instance_unverified"}
    root = RECOVERY_ROOT
    if os.environ.get("NIJA_KRAKEN_HISTORY_RECOVERY_DIR") != str(root):
        return {**result, "reason": "identity_request_consumer_directory_unverified"}
    try:
        info = root.lstat()
        if (root.is_symlink() or root.resolve() != root or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077):
            return {**result, "reason": "private_recovery_directory_required"}
        output = root / (IDENTITY_REQUEST + ".identity.evidence.json")
        if output.exists() or output.is_symlink():
            output_info = output.lstat()
            if (output.is_symlink() or output_info.st_uid != os.geteuid()
                    or stat.S_IMODE(output_info.st_mode) & 0o077 or output_info.st_nlink != 1):
                return {**result, "reason": "private_identity_receipt_required"}
            row = json.loads(_read_regular(output, 8192))
            if (not isinstance(row, dict) or row.get("request_id") != IDENTITY_REQUEST
                    or row.get("account_scope") != "platform:kraken"
                    or row.get("trading_authorized") is not False or row.get("diagnostic_only") is not True
                    or row.get("independent_certification_complete") is not False
                    or row.get("collector_installed") is not False):
                return {**result, "reason": "identity_receipt_invalid"}
            observation = row.get("observation")
            stamp = observation.get("observed_at_epoch") if isinstance(observation, dict) else None
            fresh = type(stamp) in (float, int) and 0 <= time.time() - stamp <= 60
            matched = (row.get("collection_succeeded") is True
                       and row.get("configured_account_and_key_match") is True
                       and isinstance(observation, dict) and observation.get("verified") is True
                       and observation.get("read_only") is True
                       and observation.get("scope_verified") is True
                       and observation.get("account") == "platform:kraken"
                       and observation.get("source") == "authenticated_broker"
                       and observation.get("provider_id") == "kraken-account-identity-v480-private-recovery-v491"
                       and fresh)
            failure = row.get("failure_code")
            failure = failure if isinstance(failure, str) and failure in {
                "authenticated_client_unavailable", "broker_scope_mismatch", "broker_scope_changed",
                "authenticated_identity_read_failed", "authenticated_identity_read_unverified",
                "authenticated_api_key_identity_missing", "approved_api_key_identity_mismatch",
                "approved_broker_account_mismatch", "key_expiry_unverified", "key_expired",
                "authenticated_account_identifier_invalid", "observation_clock_invalid",
                "observation_clock_invalid_or_stale", "identity_comparison_failed",
            } else "identity_comparison_unverified"
            return {
                **result, "status": "IDENTITY_RECEIPT", "configured_account_key_match": matched,
                "fresh": fresh, "reason": "saved_binding_match" if matched else failure,
            }
        claim = root / (IDENTITY_REQUEST + ".identity.claimed.json")
        if claim.exists() or claim.is_symlink():
            return {**result, "status": "CLAIMED", "reason": "consumed_request_never_replayed"}
        if not publish:
            return {**result, "status": "PENDING", "reason": "identity_receipt_not_available"}
        for relative, expected in {
            "bot/kraken_identity_request_recovery_v491.py":
                "4a129bd110b6aeb8fba96ee24fdf11f32c69346e9c5c5716adaedf7642d6f62c",
            "bot/runtime_kraken_deferred_fill_proof_recovery_v363_patch.py":
                "8e44f8f570ada43f8fe698d4b2488c0097895d964ff3eb781e6bacd934d922e4",
        }.items():
            if hashlib.sha256(_read_regular(APP_ROOT / relative, MAX_BYTES)).hexdigest() != expected:
                return {**result, "reason": "identity_consumer_source_changed"}
        binding = root / "approved-binding-platform-20261028.json"
        binding_info = binding.lstat()
        if (binding.is_symlink() or binding_info.st_uid != os.geteuid()
                or stat.S_IMODE(binding_info.st_mode) & 0o077 or binding_info.st_nlink != 1):
            return {**result, "reason": "private_saved_binding_required"}
        # The consumer validates the saved inventory and performs the comparison.
        # Its presence is NOT independent operator approval.
        _read_regular(binding, 4096)
        fd = os.open(root / "collector.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            lock_info = os.fstat(fd)
            if (not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.geteuid()
                    or stat.S_IMODE(lock_info.st_mode) & 0o077 or lock_info.st_nlink != 1):
                return {**result, "reason": "private_collector_lock_required"}
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if any(path.exists() or path.is_symlink() for path in (claim, output)):
                return {**result, "reason": "consumed_request_never_replayed"}
            for name in ("request.json", "exact_request.json", "identity_request.json"):
                if (root / name).exists() or (root / name).is_symlink():
                    return {**result, "reason": "existing_recovery_request_preserved"}
            request = {
                "request_id": IDENTITY_REQUEST, "account_scope": "platform:kraken",
                "created_at": time.time(), "max_pages": 1,
            }
            target = root / "identity_request.json"
            out = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(out, "w") as stream:
                json.dump(request, stream)
                stream.flush()
                os.fsync(stream.fileno())
            directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            os.close(fd)
        return {**result, "status": "PENDING", "reason": "existing_broker_identity_read_requested",
                "request_created": True}
    except FileNotFoundError:
        return {**result, "reason": "required_identity_recovery_file_missing"}
    except BlockingIOError:
        return {**result, "reason": "existing_collector_busy"}
    except (OSError, ValueError, TypeError):
        return {**result, "reason": "identity_probe_failed_closed"}


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--render-api"]:
        report = inspect_render_api()
    elif sys.argv[1:] in (["--request-identity"], ["--identity-result"]):
        report = identity_probe(publish=sys.argv[1:] == ["--request-identity"])
    else:
        report = inspect_instance()
    print(json.dumps(report, sort_keys=True))
