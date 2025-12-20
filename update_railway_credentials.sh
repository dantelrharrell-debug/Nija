#!/bin/bash
# Update Railway credentials with correct format

echo "🚀 Updating Railway environment variables..."
echo ""

# API Key
railway variables set COINBASE_API_KEY="organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/05067708-2a5d-43a5-a4c6-732176c05e7c"

# API Secret (PEM format with literal newlines)
railway variables set COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIIpbqWDgEUayl0/GuwoWe04zjdwyliPABAzHTRlzhJbFoAoGCCqGSM49
AwEHoUQDQgAEqoQqw6ZbWDfB1ElbpHfYAJCBof7ala7v5e3TqqiWiYqtprUajjD+
mqoVbKN6pqHMcnFwC86rM/jRId+1rgf31A==
-----END EC PRIVATE KEY-----"

echo ""
echo "✅ Railway credentials updated!"
echo "🔄 Railway will auto-restart the bot"
echo "⏱️  Wait ~30 seconds, then check: railway logs -f"
