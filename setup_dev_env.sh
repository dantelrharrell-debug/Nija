#!/bin/bash
# setup_dev_env.sh
# All-in-one VS Code + Pylance stable setup

set -e

WORKSPACE="${PWD}"
PYLANCE_VERSION="2025.9.1"

echo "=== STEP 1: Check VS Code installation ==="
if ! command -v code &> /dev/null; then
    echo "[ERROR] VS Code CLI not found. Install VS Code and add 'code' to PATH."
    exit 1
fi

echo "=== STEP 2: Install Python extension if missing ==="
if ! code --list-extensions | grep -q "ms-python.python"; then
    echo "[INFO] Installing Python extension..."
    code --install-extension ms-python.python
else
    echo "[INFO] Python extension already installed"
fi

echo "=== STEP 3: Install / downgrade Pylance ==="
code --install-extension ms-python.vscode-pylance@"$PYLANCE_VERSION" --force
echo "[INFO] Pylance pinned to $PYLANCE_VERSION"

echo "=== STEP 4: Create workspace settings.json ==="
mkdir -p "$WORKSPACE/.vscode"
cat > "$WORKSPACE/.vscode/settings.json" <<EOL
{
    "python.languageServer": "Pylance",
    "python.analysis.typeCheckingMode": "basic",
    "python.analysis.diagnosticMode": "workspace",
    "python.analysis.autoImportCompletions": true,
    "python.analysis.useLibraryCodeForTypes": true,
    "python.analysis.stubPath": "\${workspaceFolder}/typings",
    "python.analysis.logLevel": "Error",
    "python.analysis.indexing": true,
    "python.analysis.downloadMissingImports": true
}
EOL
echo "[INFO] Workspace settings applied"

echo "=== STEP 5: Install dev dependencies (if requirements-dev.txt exists) ==="
if [ -f "$WORKSPACE/requirements-dev.txt" ]; then
    echo "[INFO] Installing dev dependencies..."
    pip install -r "$WORKSPACE/requirements-dev.txt"
else
    echo "[WARNING] requirements-dev.txt not found. Skipping pip install."
fi

echo "=== SETUP COMPLETE ==="
echo "Open VS Code and reload window: Ctrl+Shift+P → Reload Window"
