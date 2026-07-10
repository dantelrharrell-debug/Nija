"""Canonical writer-authority bootstrap for the active Render entrypoint.

The production path is ``main.py -> bot.bot -> bot.bot_main``.  That path must
establish the Redis single-writer lease before any Kraken nonce singleton is
created or inspected.  This module provides that missing ordering contract.

Safety properties
-----------------
* Redis lock acquisition is atomic (Lua + SET under one Redis transaction).
* An active holder is never force-deleted by this module.
* The process remains fail-closed in standby while Redis/lock authority is
  unavailable.
* Heartbeat renewal verifies exact lock ownership before extending the TTL.
* Release is compare-and-delete; a process can never delete another writer's
  lock.
* Local fallback is available only through the explicit operator flags
  ``NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK`` and
  ``NIJA_CONFIRM_BYPASS_RISKS``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("nija.entrypoint_writer_authority")

_MARKER = "20260710u"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_GENERATION_KEY_DEFAULT = "nija:lease:generation"


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _cfg_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.environ.get(name, str(default)) or default))
    except (TypeError, ValueError):
        return max(minimum, default)


def _cfg_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(minimum, int(float(os.environ.get(name, str(default)) or default)))
    except (TypeError, ValueError):
        return max(minimum, default)


def _live_mode() -> bool:
    return (
        _truthy("LIVE_CAPITAL_VERIFIED")
        and not _truthy("DRY_RUN_MODE")
        and not _truthy("PAPER_MODE")
    )


def _writer_scope() -> str:
    configured = os.environ.get("NIJA_WRITER_LOCK_SCOPE", "").strip()
    if configured:
        return configured
    raw = (
        os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
        or os.environ.get("KRAKEN_API_KEY", "").strip()
        or "default"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _instance_identity() -> tuple[dict[str, str], str, str]:
    try:
        from bot.instance_identity import current_instance_identity, format_instance_identity

        identity = dict(current_instance_identity() or {})
        owner = str(format_instance_identity(identity) or "").strip()
    except Exception:
        identity = {}
        owner = ""

    instance_id = (
        str(identity.get("instance_id") or "").strip()
        or os.environ.get("RENDER_INSTANCE_ID", "").strip()
        or os.environ.get("HOSTNAME", "").strip()
        or f"pid-{os.getpid()}"
    )
    if not owner:
        owner = f"instance={instance_id}|pid={os.getpid()}"
    identity.setdefault("instance_id", instance_id)
    return identity, owner, instance_id


def _connect_redis(timeout_s: float = 3.0):
    try:
        from bot.redis_env import get_redis_url
        from bot.redis_runtime import connect_redis_with_fallback
    except ImportError:
        from redis_env import get_redis_url  # type: ignore[import]
        from redis_runtime import connect_redis_with_fallback  # type: ignore[import]

    redis_url = str(get_redis_url() or "").strip()
    if not redis_url:
        return None, "", "redis_url_missing"

    try:
        client, effective_url = connect_redis_with_fallback(
            url=redis_url,
            decode_responses=True,
            socket_timeout=timeout_s,
            socket_connect_timeout=timeout_s,
            retries=1,
            delay_s=0.0,
            log=lambda msg: logger.debug("entrypoint writer Redis: %s", msg),
        )
        client.ping()
        return client, str(effective_url or redis_url), ""
    except Exception as exc:
        return None, redis_url, f"redis_unavailable:{type(exc).__name__}:{exc}"


@dataclass(frozen=True)
class EntrypointWriterAuthorityResult:
    acquired: bool
    token: str = ""
    generation: int = 0
    instance_id: str = ""
    lock_key: str = ""
    holder: str = ""
    pttl_ms: int = -2
    error: str = ""
    local_fallback: bool = False


class EntrypointWriterAuthority:
    """Own and maintain the Redis writer lease for ``bot_main``."""

    def __init__(self) -> None:
        self._state_lock = threading.RLock()
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._client: Any = None
        self._result: Optional[EntrypointWriterAuthorityResult] = None
        self._lock_key = ""
        self._meta_key = ""
        self._lock_value = ""
        self._token = ""
        self._generation = 0
        self._ttl_s = 60
        self._identity: dict[str, str] = {}
        self._owner = ""
        self._instance_id = ""
        self._acquired_at = 0.0
        self._local_fallback = False

    @property
    def acquired(self) -> bool:
        return bool(self._result and self._result.acquired and not self._lost.is_set())

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    @property
    def result(self) -> Optional[EntrypointWriterAuthorityResult]:
        return self._result

    def acquire_with_standby(
        self,
        *,
        shutdown_event: Optional[threading.Event] = None,
    ) -> EntrypointWriterAuthorityResult:
        """Acquire authority before nonce startup, retrying in fail-closed standby.

        ``NIJA_ENTRYPOINT_WRITER_STANDBY_MAX_S=0`` (the default) keeps the
        process alive indefinitely while trading remains blocked.  Set a positive
        value to request a bounded standby window.
        """

        if self.acquired:
            assert self._result is not None
            return self._result

        standby_limit_s = _cfg_float(
            "NIJA_ENTRYPOINT_WRITER_STANDBY_MAX_S", 0.0, minimum=0.0
        )
        retry_s = _cfg_float(
            "NIJA_ENTRYPOINT_WRITER_STANDBY_RETRY_S", 5.0, minimum=0.5
        )
        started = time.monotonic()
        attempt = 0
        last_result = EntrypointWriterAuthorityResult(
            acquired=False,
            error="not_attempted",
        )

        while True:
            if shutdown_event is not None and shutdown_event.is_set():
                return EntrypointWriterAuthorityResult(
                    acquired=False,
                    error="shutdown_requested",
                )

            attempt += 1
            last_result = self.acquire_once()
            if last_result.acquired:
                logger.critical(
                    "ENTRYPOINT_WRITER_AUTHORITY_READY marker=%s token_prefix=%s generation=%s "
                    "instance=%s local_fallback=%s",
                    _MARKER,
                    last_result.token[:8],
                    last_result.generation,
                    last_result.instance_id,
                    last_result.local_fallback,
                )
                print(
                    f"[NIJA-PRINT] ENTRYPOINT_WRITER_AUTHORITY_READY marker={_MARKER} "
                    f"generation={last_result.generation} local_fallback={str(last_result.local_fallback).lower()}",
                    flush=True,
                )
                return last_result

            elapsed = time.monotonic() - started
            if standby_limit_s > 0 and elapsed >= standby_limit_s:
                logger.critical(
                    "ENTRYPOINT_WRITER_AUTHORITY_STANDBY_EXHAUSTED marker=%s attempts=%d "
                    "elapsed=%.1fs error=%s holder=%s pttl_ms=%s",
                    _MARKER,
                    attempt,
                    elapsed,
                    last_result.error,
                    last_result.holder,
                    last_result.pttl_ms,
                )
                return last_result

            logger.warning(
                "ENTRYPOINT_WRITER_AUTHORITY_STANDBY marker=%s attempt=%d elapsed=%.1fs "
                "error=%s holder=%s pttl_ms=%s next_retry_s=%.1f",
                _MARKER,
                attempt,
                elapsed,
                last_result.error,
                last_result.holder,
                last_result.pttl_ms,
                retry_s,
            )
            if shutdown_event is not None:
                shutdown_event.wait(retry_s)
            else:
                time.sleep(retry_s)

    def acquire_once(self) -> EntrypointWriterAuthorityResult:
        with self._state_lock:
            if self.acquired:
                assert self._result is not None
                return self._result

            client, _effective_url, connect_error = _connect_redis(
                timeout_s=_cfg_float(
                    "NIJA_ENTRYPOINT_WRITER_REDIS_TIMEOUT_S", 3.0, minimum=0.5
                )
            )
            if client is None:
                fallback = self._maybe_grant_local_fallback(connect_error)
                if fallback is not None:
                    return fallback
                return EntrypointWriterAuthorityResult(
                    acquired=False,
                    error=connect_error or "redis_unavailable",
                )

            identity, owner, instance_id = _instance_identity()
            scope = _writer_scope()
            lock_key = (
                os.environ.get("NIJA_WRITER_LOCK_KEY", "").strip()
                or f"nija:writer_lock:{scope}"
            )
            meta_key = (
                os.environ.get("NIJA_WRITER_LOCK_META_KEY", "").strip()
                or f"nija:writer_lock_meta:{scope}"
            )
            fencing_key = (
                os.environ.get("NIJA_WRITER_FENCING_KEY", "").strip()
                or f"nija:writer_fence:{scope}"
            )
            generation_key = (
                os.environ.get("NIJA_LEASE_GENERATION_KEY", "").strip()
                or _GENERATION_KEY_DEFAULT
            )

            ttl_s = self._resolve_ttl_s()
            wait_s = _cfg_float(
                "NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S", 15.0, minimum=0.0
            )
            retry_s = _cfg_float(
                "NIJA_ENTRYPOINT_WRITER_LOCK_RETRY_S", 0.5, minimum=0.1
            )
            deadline = time.monotonic() + wait_s
            holder = ""
            pttl_ms = -2

            acquire_script = """
            if redis.call('EXISTS', KEYS[1]) == 1 then
                local holder = redis.call('GET', KEYS[1]) or ''
                local pttl = redis.call('PTTL', KEYS[1]) or -2
                local generation = redis.call('GET', KEYS[3]) or '0'
                return {0, holder, pttl, generation}
            end
            local token = redis.call('INCR', KEYS[2])
            local generation = redis.call('INCR', KEYS[3])
            local value = tostring(token) .. ':' .. ARGV[1]
            redis.call('SET', KEYS[1], value, 'EX', tonumber(ARGV[2]))
            local pttl = redis.call('PTTL', KEYS[1]) or -2
            return {token, value, pttl, generation}
            """

            while True:
                try:
                    raw = client.eval(
                        acquire_script,
                        3,
                        lock_key,
                        fencing_key,
                        generation_key,
                        owner,
                        str(ttl_s),
                    )
                except Exception as exc:
                    return EntrypointWriterAuthorityResult(
                        acquired=False,
                        lock_key=lock_key,
                        error=f"redis_acquire_failed:{type(exc).__name__}:{exc}",
                    )

                token = self._as_int(raw[0] if isinstance(raw, (list, tuple)) and raw else 0)
                holder = self._as_text(raw[1] if isinstance(raw, (list, tuple)) and len(raw) > 1 else "")
                pttl_ms = self._as_int(raw[2] if isinstance(raw, (list, tuple)) and len(raw) > 2 else -2, default=-2)
                generation = self._as_int(raw[3] if isinstance(raw, (list, tuple)) and len(raw) > 3 else 0)

                if token > 0:
                    return self._activate_distributed_authority(
                        client=client,
                        token=str(token),
                        generation=generation,
                        identity=identity,
                        owner=owner,
                        instance_id=instance_id,
                        scope=scope,
                        lock_key=lock_key,
                        meta_key=meta_key,
                        generation_key=generation_key,
                        ttl_s=ttl_s,
                    )

                if time.monotonic() >= deadline:
                    return EntrypointWriterAuthorityResult(
                        acquired=False,
                        instance_id=instance_id,
                        lock_key=lock_key,
                        holder=holder,
                        pttl_ms=pttl_ms,
                        error="active_writer_lock_held",
                    )
                time.sleep(retry_s)

    def _resolve_ttl_s(self) -> int:
        ttl_raw = os.environ.get("NIJA_WRITER_LOCK_TTL_S", "").strip()
        if ttl_raw:
            return _cfg_int("NIJA_WRITER_LOCK_TTL_S", 60, minimum=15)
        lease_ms = _cfg_int("NIJA_REDIS_LEASE_TTL_MS", 60000, minimum=15000)
        return max(15, int((lease_ms + 999) // 1000))

    @staticmethod
    def _as_text(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value or "")

    @staticmethod
    def _as_int(value: Any, *, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _activate_distributed_authority(
        self,
        *,
        client: Any,
        token: str,
        generation: int,
        identity: dict[str, str],
        owner: str,
        instance_id: str,
        scope: str,
        lock_key: str,
        meta_key: str,
        generation_key: str,
        ttl_s: int,
    ) -> EntrypointWriterAuthorityResult:
        self._client = client
        self._token = token
        self._generation = generation
        self._identity = identity
        self._owner = owner
        self._instance_id = instance_id
        self._lock_key = lock_key
        self._meta_key = meta_key
        self._lock_value = f"{token}:{owner}"
        self._ttl_s = ttl_s
        self._acquired_at = time.time()
        self._local_fallback = False
        self._lost.clear()
        self._stop.clear()

        self._publish_env(scope=scope, generation_key=generation_key, fallback=False)
        self._write_metadata()
        self._start_heartbeat()

        result = EntrypointWriterAuthorityResult(
            acquired=True,
            token=token,
            generation=generation,
            instance_id=instance_id,
            lock_key=lock_key,
        )
        self._result = result
        return result

    def _maybe_grant_local_fallback(
        self, reason: str
    ) -> Optional[EntrypointWriterAuthorityResult]:
        if not (
            _truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK")
            and _truthy("NIJA_CONFIRM_BYPASS_RISKS")
        ):
            return None

        identity, owner, instance_id = _instance_identity()
        token = str(int(time.time() * 1000))
        generation = int(token)
        scope = _writer_scope()
        self._token = token
        self._generation = generation
        self._identity = identity
        self._owner = owner
        self._instance_id = instance_id
        self._lock_key = (
            os.environ.get("NIJA_WRITER_LOCK_KEY", "").strip()
            or f"nija:writer_lock:{scope}"
        )
        self._meta_key = (
            os.environ.get("NIJA_WRITER_LOCK_META_KEY", "").strip()
            or f"nija:writer_lock_meta:{scope}"
        )
        self._lock_value = f"{token}:{owner}"
        self._acquired_at = time.time()
        self._local_fallback = True
        self._lost.clear()
        self._publish_env(
            scope=scope,
            generation_key=os.environ.get(
                "NIJA_LEASE_GENERATION_KEY", _GENERATION_KEY_DEFAULT
            ),
            fallback=True,
        )
        logger.critical(
            "ENTRYPOINT_WRITER_AUTHORITY_LOCAL_FALLBACK marker=%s reason=%s instance=%s",
            _MARKER,
            reason,
            instance_id,
        )
        result = EntrypointWriterAuthorityResult(
            acquired=True,
            token=token,
            generation=generation,
            instance_id=instance_id,
            lock_key=self._lock_key,
            local_fallback=True,
        )
        self._result = result
        return result

    def _publish_env(self, *, scope: str, generation_key: str, fallback: bool) -> None:
        now = str(time.time())
        os.environ["NIJA_WRITER_FENCING_TOKEN"] = self._token
        os.environ["NIJA_WRITER_OWNER_ID"] = self._owner
        os.environ["NIJA_WRITER_INSTANCE_ID"] = self._instance_id
        os.environ["NIJA_WRITER_LEASE_GENERATION"] = str(self._generation)
        os.environ["NIJA_LEASE_GENERATION_KEY"] = str(generation_key)
        os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "1"
        os.environ["NIJA_LOCK_ACQUIRED"] = "true"
        os.environ["NIJA_WRITER_LOCK_KEY"] = self._lock_key
        os.environ["NIJA_WRITER_LOCK_META_KEY"] = self._meta_key
        os.environ["NIJA_WRITER_LOCK_SCOPE"] = scope
        os.environ["NIJA_WRITER_LOCK_TTL_S"] = str(self._ttl_s)
        os.environ["NIJA_WRITER_LOCK_ACQUIRED_AT"] = str(self._acquired_at)
        os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
        os.environ["NIJA_WRITER_HEARTBEAT_LAST_TS"] = now
        os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = now
        if fallback:
            os.environ["NIJA_WRITER_FENCING_TOKEN_FALLBACK"] = "1"
            os.environ["NIJA_LOCK_BYPASS_MODE"] = (
                "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK"
            )
        else:
            os.environ.pop("NIJA_WRITER_FENCING_TOKEN_FALLBACK", None)
            os.environ.pop("NIJA_LOCK_BYPASS_MODE", None)

    def _metadata_payload(self) -> str:
        return json.dumps(
            {
                "token": self._token,
                "instance": self._identity,
                "instance_id": self._instance_id,
                "generation": self._generation,
                "acquired_at": self._acquired_at,
                "heartbeat_at": time.time(),
                "lock_ttl_s": self._ttl_s,
                "source": "entrypoint_writer_authority",
            },
            sort_keys=True,
        )

    def _write_metadata(self) -> None:
        if self._client is None or not self._meta_key:
            return
        try:
            self._client.set(
                self._meta_key,
                self._metadata_payload(),
                ex=max(15, self._ttl_s),
            )
        except Exception as exc:
            logger.warning(
                "ENTRYPOINT_WRITER_AUTHORITY_METADATA_WRITE_FAILED marker=%s err=%s",
                _MARKER,
                exc,
            )

    def _start_heartbeat(self) -> None:
        if self._local_fallback:
            return
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="entrypoint-writer-lock-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        interval_s = _cfg_float(
            "NIJA_WRITER_HEARTBEAT_INTERVAL_S",
            min(5.0, max(1.0, self._ttl_s / 3.0)),
            minimum=1.0,
        )
        max_failures = _cfg_int(
            "NIJA_WRITER_LOCK_HEARTBEAT_MAX_FAILURES", 12, minimum=3
        )
        failures = 0

        while not self._stop.is_set():
            ok, reason = self._heartbeat_tick()
            if ok:
                failures = 0
            else:
                failures += 1
                logger.warning(
                    "ENTRYPOINT_WRITER_HEARTBEAT_FAILED marker=%s failures=%d/%d reason=%s",
                    _MARKER,
                    failures,
                    max_failures,
                    reason,
                )
                if failures >= max_failures:
                    self._mark_lost(reason)
                    return
            self._stop.wait(interval_s)

    def _heartbeat_tick(self) -> tuple[bool, str]:
        os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = str(time.time())
        if self._client is None:
            return False, "redis_client_missing"

        script = """
        local current = redis.call('GET', KEYS[1])
        if not current then return -1 end
        if current ~= ARGV[1] then return 0 end
        redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
        if KEYS[2] and KEYS[2] ~= '' then
            redis.call('SET', KEYS[2], ARGV[3], 'EX', tonumber(ARGV[2]))
        end
        return 1
        """
        try:
            code = int(
                self._client.eval(
                    script,
                    2,
                    self._lock_key,
                    self._meta_key,
                    self._lock_value,
                    str(self._ttl_s),
                    self._metadata_payload(),
                )
                or 0
            )
            if code == 1:
                now = str(time.time())
                os.environ["NIJA_WRITER_HEARTBEAT_LAST_TS"] = now
                os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = now
                os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
                return True, ""
            if code == -1:
                reacquired = bool(
                    self._client.set(
                        self._lock_key,
                        self._lock_value,
                        ex=self._ttl_s,
                        nx=True,
                    )
                )
                if reacquired:
                    self._write_metadata()
                    now = str(time.time())
                    os.environ["NIJA_WRITER_HEARTBEAT_LAST_TS"] = now
                    os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = now
                    os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
                    logger.warning(
                        "ENTRYPOINT_WRITER_LOCK_REACQUIRED marker=%s token_prefix=%s",
                        _MARKER,
                        self._token[:8],
                    )
                    return True, ""
                return False, "lock_expired_and_reacquire_lost"
            return False, "lock_owned_by_different_writer"
        except Exception as exc:
            return False, f"redis_heartbeat_error:{type(exc).__name__}:{exc}"

    def _mark_lost(self, reason: str) -> None:
        self._lost.set()
        os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "0"
        os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"
        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
        os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
        os.environ.pop("NIJA_WRITER_FENCING_TOKEN", None)
        logger.critical(
            "ENTRYPOINT_WRITER_AUTHORITY_LOST marker=%s reason=%s",
            _MARKER,
            reason,
        )
        try:
            from bot.single_execution_authority_kernel import get_seak

            get_seak().emergency_halt(f"entrypoint_writer_authority_lost:{reason}")
        except Exception as exc:
            logger.error(
                "ENTRYPOINT_WRITER_AUTHORITY_SEAK_HALT_FAILED marker=%s err=%s",
                _MARKER,
                exc,
            )

    def release(self) -> bool:
        """Stop heartbeat and compare-and-delete only this process's lock."""

        with self._state_lock:
            self._stop.set()
            released = False
            if self._client is not None and self._lock_key and self._lock_value:
                script = """
                local current = redis.call('GET', KEYS[1])
                if not current or current ~= ARGV[1] then return 0 end
                redis.call('DEL', KEYS[1])
                if KEYS[2] and KEYS[2] ~= '' then redis.call('DEL', KEYS[2]) end
                return 1
                """
                try:
                    released = bool(
                        int(
                            self._client.eval(
                                script,
                                2,
                                self._lock_key,
                                self._meta_key,
                                self._lock_value,
                            )
                            or 0
                        )
                    )
                except Exception as exc:
                    logger.warning(
                        "ENTRYPOINT_WRITER_AUTHORITY_RELEASE_FAILED marker=%s err=%s",
                        _MARKER,
                        exc,
                    )

            os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "0"
            os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"
            os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = "0"
            os.environ.pop("NIJA_WRITER_FENCING_TOKEN", None)
            os.environ.pop("NIJA_WRITER_FENCING_TOKEN_FALLBACK", None)
            logger.info(
                "ENTRYPOINT_WRITER_AUTHORITY_RELEASED marker=%s released=%s local_fallback=%s",
                _MARKER,
                released,
                self._local_fallback,
            )
            return released or self._local_fallback


_SINGLETON: Optional[EntrypointWriterAuthority] = None
_SINGLETON_LOCK = threading.Lock()


def get_entrypoint_writer_authority() -> EntrypointWriterAuthority:
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is None:
            _SINGLETON = EntrypointWriterAuthority()
        return _SINGLETON
