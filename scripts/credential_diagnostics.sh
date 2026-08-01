#!/bin/bash

# Credential-presence diagnostics shared by start.sh. Values are never printed.

nija_first_nonempty_env_name() {
    local name
    local value
    for name in "$@"; do
        value="${!name-}"
        if [ -n "${value//[[:space:]]/}" ]; then
            printf '%s' "$name"
            return 0
        fi
    done
    return 1
}

nija_print_kraken_user_credential_status() {
    local label="$1"
    local short_prefix="$2"
    local full_prefix="$3"
    local key_name=""
    local secret_name=""
    local key_value=""
    local secret_value=""

    key_name=$(nija_first_nonempty_env_name \
        "KRAKEN_USER_${short_prefix}_API_KEY" \
        "KRAKEN_USER_${full_prefix}_API_KEY" || true)
    secret_name=$(nija_first_nonempty_env_name \
        "KRAKEN_USER_${short_prefix}_API_SECRET" \
        "KRAKEN_USER_${full_prefix}_API_SECRET" || true)

    echo "   👤 KRAKEN (${label}):"
    if [ -n "$key_name" ] && [ -n "$secret_name" ]; then
        key_value="${!key_name}"
        secret_value="${!secret_name}"
        echo "      ✅ Configured (Key: ${#key_value} chars via ${key_name}, Secret: ${#secret_value} chars via ${secret_name})"
        return 0
    fi

    echo "      ❌ Incomplete configuration (Key: ${key_name:-missing}, Secret: ${secret_name:-missing})"
    # Diagnostics are informational; an optional user account must not abort start.sh.
    return 0
}
