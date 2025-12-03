#!/bin/bash

echo "🔧 Building Docker image..."
docker build -t nija-trading-bot:latest .

echo "📦 Staging all changes..."
git add .

echo "📝 Committing with timestamp..."
git commit -m "Automated commit: $(date '+%Y-%m-%d %H:%M:%S')"

echo "🚀 Pushing to main branch..."
git push origin main

echo "✅ Done!"
