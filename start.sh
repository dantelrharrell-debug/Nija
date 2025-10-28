#!/bin/bash
# start.sh

echo "🌟 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "🌟 Starting Nija bot..."
python3 nija_live_snapshot.py
