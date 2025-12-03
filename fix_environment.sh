#!/usr/bin/env bash
set -euo pipefail

GITHUB_USER="dantelrharrell-debug"
REPO_NAME="coinbase_advanced_py"
PACKAGE_DEST="/workspaces/Nija/vendor/${REPO_NAME}"
PACKAGE_NAME="coinbase_advanced_py"  # Python package name if different

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Please install Python 3."
    exit 1
fi

if [ -z "${GITHUB_TOKEN:-}" ]; then
    echo "ERROR: Please set your GITHUB_TOKEN environment variable with a valid GitHub PAT (repo scope for private repos)."
    exit 1
fi

echo "======= Starting Environment Fix (Super-Fast Mode) ======="

CLEANUP_TMP() { [ -n "${TMP_ASKPASS:-}" ] && rm -f "$TMP_ASKPASS"; }
trap CLEANUP_TMP EXIT

if [ ! -d "$PACKAGE_DEST" ]; then
    echo "Cloning $REPO_NAME into $PACKAGE_DEST ..."
    TMP_ASKPASS=$(mktemp)
    echo "echo \$GITHUB_TOKEN" > "$TMP_ASKPASS"
    chmod +x "$TMP_ASKPASS"
    GIT_ASKPASS="$TMP_ASKPASS" git clone --depth 1 "https://github.com/${GITHUB_USER}/${REPO_NAME}.git" "$PACKAGE_DEST"
    CLEANUP_TMP
else
    cd "$PACKAGE_DEST"
    UPSTREAM=$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || echo "")
    if [ -n "$UPSTREAM" ] && [ "$(git rev-list --count HEAD..$UPSTREAM)" -gt 0 ]; then
        echo "Updating repo..."
        TMP_ASKPASS=$(mktemp)
        echo "echo \$GITHUB_TOKEN" > "$TMP_ASKPASS"
        chmod +x "$TMP_ASKPASS"
        GIT_ASKPASS="$TMP_ASKPASS" git pull --rebase
        CLEANUP_TMP
    else
        echo "Repo is already up to date, skipping git pull."
    fi
    cd - >/dev/null
fi

PIP_VERSION=$(python3 -m pip --version | awk '{print $2}')
REQUIRED_PIP="23.0.0"
if [ "$(printf '%s\n' "$REQUIRED_PIP" "$PIP_VERSION" | sort -V | head -n1)" != "$REQUIRED_PIP" ]; then
    echo "Upgrading pip, setuptools, and wheel..."
    python3 -m pip install --upgrade pip setuptools wheel
else
    echo "Pip is recent, skipping upgrade."
fi

if ! python3 -m pip show "$PACKAGE_NAME" &>/dev/null; then
    echo "Installing package $PACKAGE_NAME..."
    python3 -m pip install -e "$PACKAGE_DEST"
else
    echo "Package $PACKAGE_NAME already installed, upgrading only if needed..."
    python3 -m pip install -e "$PACKAGE_DEST" --upgrade
fi

echo "Testing Python import..."
python3 -c "import $PACKAGE_NAME; print('Imported:', $PACKAGE_NAME.__file__)"

echo "======= Environment Fix Complete (Super-Fast Mode) ======="
