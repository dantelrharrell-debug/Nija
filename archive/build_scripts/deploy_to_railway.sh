#!/bin/bash
# Deploy NIJA to Railway for 24/7 Trading

echo "🚀 Deploying NIJA Ultimate Trading Logic™ to Railway..."
echo ""

# Step 1: Login to Railway
echo "Step 1: Logging in to Railway..."
railway login

# Step 2: Link to your Railway project (or create new one)
echo ""
echo "Step 2: Linking to Railway project..."
railway link

# Step 3: Set environment variables
echo ""
echo "Step 3: Setting environment variables..."
railway variables set COINBASE_API_KEY="9e33d60c-c9d7-4318-a2d5-24e1e53d2206"
railway variables set COINBASE_API_SECRET="-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIKrWQ2OeX7kqTob0aXR6A238b698ePPLutcEP1qq4gfLoAoGCCqGSM49
AwEHoUQDQgAEuQAqrVE522HzPw3+AOIOEo+a1FhOrtKShm5VkFJC7PkyAFc0pDH9
8lCbZUbOBox1ut7nAHTZHWakTE1AZl7gbA==
-----END EC PRIVATE KEY-----"
railway variables set LIVE_TRADING=1

# Step 4: Deploy
echo ""
echo "Step 4: Deploying to Railway..."
railway up

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Monitor logs with: railway logs --follow"
