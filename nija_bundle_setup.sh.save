#!/bin/bash

# Go to the script's directory
cd "$(dirname "$0")"

echo "📦 Installing Python dependencies..."
python3 -m pip install --upgrade pip
pip3 install -r requirements.txt

echo "📁 Making vendor folder if it doesn't exist..."
mkdir -p vendor

echo "✅ Setup complete! You can now run:"
echo "   python3 nija_bot.py"
