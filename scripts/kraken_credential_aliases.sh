#!/usr/bin/env bash
# Sourced by both production front doors; never combine credential namespaces.

_promote_kraken_credential_pair() {
    if [[ -n "${KRAKEN_PLATFORM_API_KEY:-}" || -n "${KRAKEN_PLATFORM_API_SECRET:-}" ]]; then
        # Partial canonical configuration must be repaired by the operator.
        return 0
    fi

    local key_alias secret_alias
    while (( $# >= 2 )); do
        key_alias="$1"
        secret_alias="$2"
        shift 2
        if [[ -n "${!key_alias:-}" && -n "${!secret_alias:-}" ]]; then
            export KRAKEN_PLATFORM_API_KEY="${!key_alias}"
            export KRAKEN_PLATFORM_API_SECRET="${!secret_alias}"
            echo "Kraken credential pair normalized: ${key_alias}/${secret_alias}"
            return 0
        fi
    done
    return 0
}

_promote_kraken_credential_pair \
    KRAKEN_API_KEY KRAKEN_API_SECRET \
    KRAKEN_API_KEY KRAKEN_PRIVATE_KEY \
    KRAKEN_API_KEY KRAKEN_SECRET_KEY \
    KRAKEN_MASTER_API_KEY KRAKEN_MASTER_API_SECRET \
    KRAKEN_MASTER_KEY KRAKEN_MASTER_SECRET \
    KRAKEN_PLATFORM_KEY KRAKEN_PLATFORM_SECRET
