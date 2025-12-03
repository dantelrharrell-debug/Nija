#!/usr/bin/env bash
set -euo pipefail

# Simple, robust environment bootstrap for coinbase_advanced_py
GITHUB_USER="dantelrharrell-debug"
REPO_NAME="coinbase_advanced_py"
PACKAGE_DEST="/workspaces/Nija/vendor/${REPO_NAME}"
PACKAGE_NAME="coinbase_advanced_py"  # Python package import name (may differ from repo)

REQUIRED_PIP="23.0.0"

CLEANUP_TMP() { [ -n "${TMP_ASKPASS:-}" ] && rm -f "$TMP_ASKPASS" || true; }
trap CLEANUP_TMP EXIT

# sanity checks
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Please install Python 3."
    exit 1
fi

if [ ! -d "$PACKAGE_DEST" ]; then
    echo "Package directory $PACKAGE_DEST not found. Attempting to clone ${GITHUB_USER}/${REPO_NAME} ..."
    if [ -n "${GITHUB_TOKEN:-}" ]; then
        TMP_ASKPASS=$(mktemp)
        echo "echo \$GITHUB_TOKEN" > "$TMP_ASKPASS"
        chmod +x "$TMP_ASKPASS"
        GIT_ASKPASS="$TMP_ASKPASS" git clone --depth 1 "https://github.com/${GITHUB_USER}/${REPO_NAME}.git" "$PACKAGE_DEST"
    else
        # try unauthenticated clone (works for public repos)
        if ! git clone --depth 1 "https://github.com/${GITHUB_USER}/${REPO_NAME}.git" "$PACKAGE_DEST"; then
            echo "ERROR: Clone failed. If the repo is private, set GITHUB_TOKEN and retry."
            exit 1
        fi
    fi
else
    echo "Package directory $PACKAGE_DEST exists. Checking for upstream updates..."
    # try to update if there are upstream commits
    if [ -d "${PACKAGE_DEST}/.git" ]; then
        pushd "$PACKAGE_DEST" >/dev/null
        # fetch remote refs
        if [ -n "${GITHUB_TOKEN:-}" ]; then
            TMP_ASKPASS=$(mktemp)
            echo "echo \$GITHUB_TOKEN" > "$TMP_ASKPASS"
            chmod +x "$TMP_ASKPASS"
            GIT_ASKPASS="$TMP_ASKPASS" git fetch --all --prune
        else
            git fetch --all --prune || true
        fi

        UPSTREAM=$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || true)
        if [ -n "$UPSTREAM" ] && [ "$(git rev-list --count HEAD..$UPSTREAM || echo 0)" -gt 0 ]; then
            echo "Remote has new commits. Attempting to pull --rebase..."
            if [ -n "${GITHUB_TOKEN:-}" ]; then
                TMP_ASKPASS=$(mktemp)
                echo "echo \$GITHUB_TOKEN" > "$TMP_ASKPASS"
                chmod +x "$TMP_ASKPASS"
                GIT_ASKPASS="$TMP_ASKPASS" git pull --rebase || echo "Warning: git pull failed"
            else
                git pull --rebase || echo "Warning: git pull failed (no GITHUB_TOKEN may block private repos)"
            fi
        else
            echo "Repo is up to date."
        fi
        popd >/dev/null
    else
        echo "Warning: $PACKAGE_DEST exists but is not a git repo. Skipping update."
    fi
fi

# Ensure pip/tools are recent enough
PIP_VERSION=$(python3 -m pip --version | awk '{print $2}')
if [ "$(printf '%s\n' "$REQUIRED_PIP" "$PIP_VERSION" | sort -V | head -n1)" != "$REQUIRED_PIP" ]; then
    echo "Upgrading pip, setuptools, and wheel..."
    python3 -m pip install --upgrade pip setuptools wheel
else
    echo "Pip is recent ($PIP_VERSION), skipping upgrade."
fi

# Install or upgrade the package in editable mode (so local changes are reflected)
if python3 -m pip show "$PACKAGE_NAME" &>/dev/null; then
    INSTALLED_LOCATION=$(python3 -c "import importlib, sys; m=importlib.import_module('${PACKAGE_NAME}'); print(getattr(m, '__file__', ''))")
    echo "Package ${PACKAGE_NAME} already installed at: ${INSTALLED_LOCATION:-unknown}. Installing/refreshing from $PACKAGE_DEST ..."
fi

python3 -m pip install --upgrade -e "$PACKAGE_DEST"

# Verify import works
echo "Testing Python import..."
python3 - <<PY
try:
    import importlib, traceback
    m = importlib.import_module("$PACKAGE_NAME")
    print("Imported:", getattr(m, "__file__", "<no __file__>"))
except Exception:
    traceback.print_exc()
    raise SystemExit(2)
PY

echo "Environment bootstrap complete. Executing start.sh ..."
if [ ! -x /usr/src/app/start.sh ]; then
    echo "Warning: /usr/src/app/start.sh not executable or not found. Making executable if present."
    [ -f /usr/src/app/start.sh ] && chmod +x /usr/src/app/start.sh || echo "ERROR: start.sh missing at /usr/src/app/start.sh"
fi

exec /usr/src/app/start.sh
