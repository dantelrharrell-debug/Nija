#!/bin/bash
# Rollback Nija Bot to last working state (2025-11-12 19:53:25)

echo "Stopping current container..."
# Stop the running container (if using Docker locally)
docker stop nija_bot 2>/dev/null || echo "No container running, continuing..."

echo "Restoring working code..."
# Copy your backup of the last working code
# Replace /path/to/backup with the actual path where you saved working version
cp -r /path/to/backup/* /app/

echo "Restoring working .env..."
cat <<EOT > /app/.env
# ===== COINBASE Credentials =====
COINBASE_JWT_PEM="-----BEGIN EC PRIVATE KEY-----\nYOUR_FULL_PEM_KEY_HERE\n-----END EC PRIVATE KEY-----"
COINBASE_JWT_KID="YOUR_KEY_ID_HERE"
COINBASE_JWT_ISSUER="YOUR_ISSUER_ID_HERE"
COINBASE_ORG_ID="YOUR_ORG_ID_HERE"

# ===== OTHER ENV VARIABLES =====
# Add any other environment variables your bot needs exactly as in last working .env
EOT

echo "Rebuilding container..."
docker build -t nija_bot /app/

echo "Starting container..."
docker run -d --name nija_bot -p 5000:5000 --env-file /app/.env nija_bot

echo "Rollback complete. Check logs with:"
echo "docker logs -f nija_bot"
