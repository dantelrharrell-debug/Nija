# Deploy to Render.com - Alternative to Railway

## Why Render?
Railway has persistent Docker cache issues that survive service deletion. Render guarantees fresh builds every deployment.

---

## Quick Deploy Steps

### 1. Create Render Account
- Go to https://render.com
- Sign in with your GitHub account
- Authorize Render to access repositories

### 2. Create New Web Service
1. Click **"New +"** → **"Web Service"**
2. Connect repository: `dantelrharrell-debug/Nija`
3. Configure:
   - **Branch**: main
   - **Runtime**: Docker
   - **Instance Type**: Free (or Starter $7/month)

### 3. Add Environment Variables

Click **"Advanced"** → Add these 4 variables:

**COINBASE_API_KEY**
```
organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/4cfe95c4-23c3-4480-a13c-1259f7320c36
```

**COINBASE_API_SECRET** *(CRITICAL: Must be ONE line with \n as literal text)*
```
-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIN8qIYi2YYF+EVw3SjBFI4vGG5s5+GK67PMtJsihiqMboAoGCCqGSM49\nAwEHoUQDQgAEyX6F9fdJ6FN8iigO3bOpAgs5rURgmpbPQulXOJhVUIQrBVvdHPz3\nKBxA/l4CdmnIbdsK4d+kTK8bNygn794vPA==\n-----END EC PRIVATE KEY-----\n
```

**LIVE_TRADING**
```
1
```

**ALLOW_CONSUMER_USD**
```
true
```

### 4. Deploy
Click **"Create Web Service"** - Render will build fresh from GitHub (no cache).

---

## Verify Success

Watch logs for these **SUCCESS INDICATORS**:

```
✅ Branch: main                    (not "unknown")
✅ Commit: <actual SHA>            (not "unknown")  
✅ Account balance: $55.81         (not $10,000)
✅ Position size: $5.XX            (NOT $1.12)
✅ Coinbase Advanced Trade connected
```

**FAILURE** indicators mean cache/old code:
```
❌ Branch: unknown
❌ Commit: unknown
❌ Position size: $1.12
❌ Unknown error from broker
```

---

## If Render Also Shows $1.12

1. **Check commit SHA** in logs matches GitHub latest
2. Click **"Manual Deploy"** → **"Clear build cache & deploy"**
3. Verify environment variables set correctly
4. Ensure `LIVE_TRADING=1` is set

---

## Advantages Over Railway

✅ **No persistent cache** - Fresh builds guaranteed  
✅ **"Clear cache" button** that actually works  
✅ **Better logs** - More detailed deployment output  
✅ **Free tier** - 750 hours/month free  
✅ **Auto-deploy** from GitHub like Railway  

---

## Support

- Render Docs: https://render.com/docs
- Bot Repo: https://github.com/dantelrharrell-debug/Nija
- APEX Strategy: See APEX_V71_DOCUMENTATION.md
