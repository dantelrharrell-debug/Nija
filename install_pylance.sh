#!/bin/bash
# install_pylance.sh

echo "[INFO] Checking VS Code extensions..."
code --list-extensions | grep ms-python.python >/dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "[INFO] Installing Python extension..."
    code --install-extension ms-python.python
fi

echo "[INFO] Installing Pylance extension pinned version..."
code --install-extension ms-python.vscode-pylance@2025.9.1 --force

echo "[INFO] Done. Pylance pinned to 2025.9.1"
