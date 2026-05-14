"""Regression checks for Redis TLS kwargs hardening."""

from __future__ import annotations

import os
import sys
import types

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)
sys.modules.setdefault("redis", types.SimpleNamespace())

from bot.redis_runtime import get_redis_tls_kwargs


def _set_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def check_railway_rediss_auto_uses_tls_without_cert_validation() -> None:
    _set_env("NIJA_REDIS_TLS_CA_CERT", None)
    _set_env("NIJA_REDIS_TLS_INSECURE", "auto")
    kwargs = get_redis_tls_kwargs("rediss://default:pw@maglev.proxy.rlwy.net:12345/0")
    assert kwargs.get("ssl_cert_reqs") == "none"
    assert kwargs.get("ssl_check_hostname") is False


def check_ca_cert_enables_strict_verification() -> None:
    _set_env("NIJA_REDIS_TLS_CA_CERT", "/etc/ssl/certs/ca-certificates.crt")
    _set_env("NIJA_REDIS_TLS_INSECURE", "auto")
    kwargs = get_redis_tls_kwargs("rediss://default:pw@redis.example.com:6380/0")
    assert kwargs.get("ssl_cert_reqs") == "required"
    assert kwargs.get("ssl_ca_certs") == "/etc/ssl/certs/ca-certificates.crt"
    assert "ssl_check_hostname" not in kwargs


def check_non_railway_rediss_defaults_to_strict_verification() -> None:
    _set_env("NIJA_REDIS_TLS_CA_CERT", None)
    _set_env("NIJA_REDIS_TLS_INSECURE", "false")
    kwargs = get_redis_tls_kwargs("rediss://default:pw@redis.example.com:6380/0")
    assert kwargs == {"ssl_cert_reqs": "required"}


def check_non_tls_url_has_no_tls_kwargs() -> None:
    _set_env("NIJA_REDIS_TLS_CA_CERT", None)
    _set_env("NIJA_REDIS_TLS_INSECURE", "auto")
    kwargs = get_redis_tls_kwargs("redis://default:pw@redis.example.com:6379/0")
    assert kwargs == {}


if __name__ == "__main__":
    check_railway_rediss_auto_uses_tls_without_cert_validation()
    check_ca_cert_enables_strict_verification()
    check_non_railway_rediss_defaults_to_strict_verification()
    check_non_tls_url_has_no_tls_kwargs()
    print("✅ test_redis_tls_hardening passed")
