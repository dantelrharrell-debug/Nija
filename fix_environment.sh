#!/usr/bin/env bash
set -euo pipefail

GITHUB_USER="dantelrharrell-debug"
REPO_NAME="coinbase_advanced_py"
PACKAGE_DEST="/workspaces/Nija/vendor/${REPO_NAME}"
PACKAGE_NAME="coinbase_advanced_py"  # Set to Python package name if different

if [ -z "${GITHUB_TOKEN:-}" ]; then
    echo "ERROR: Please set your GITHUB_TOKEN environment variable with a valid GitHub PAT (repo scope for private repos)."
    exit 1
fi

echo "======= Starting Environment Fix ======="

if [ ! -d "$PACKAGE_DEST" ]; then
    echo "Cloning $REPO_NAME into $PACKAGE_DEST ..."
    git clone --depth 1 "https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com/${GITHUB_USER}/${REPO_NAME}.git" "$PACKAGE_DEST"
else
    echo "$PACKAGE_DEST already exists, skipping git clone."
fi

echo "Installing package $REPO_NAME from $PACKAGE_DEST ..."
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install -e "$PACKAGE_DEST"

echo "Verifying installation ..."
python3 -m pip show "$REPO_NAME" || echo "WARNING: Package $REPO_NAME not detected by pip."

echo "Testing Python import ..."
python3 -c "import $PACKAGE_NAME; print('Imported:', $PACKAGE_NAME.__file__)"

echo "Configuring git to use rebase on pull and updating repo..."
cd "$PACKAGE_DEST"
git config pull.rebase true
git pull --rebase || echo "Git repo is already up to date or pull not needed."
cd -  # Return to previous directory

echo "======= Environment Fix Complete ======="
