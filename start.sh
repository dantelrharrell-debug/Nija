#!/bin/bash

echo "[NIJA] Installing Coinbase Advanced SDK..."
python3 -m pip install --upgrade pip
python3 -m pip install "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git"

echo "[NIJA] Starting Nija Trading Bot..."
python3 nija_render_worker.py
