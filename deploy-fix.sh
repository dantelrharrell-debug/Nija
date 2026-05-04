#!/bin/bash
# Deploy Railway infinite restart loop fix

echo "🚀 Committing and pushing Railway fixes..."
echo ""

# Stage the changes
echo "📝 Staging bot.py changes..."
git add bot.py

# Commit with detailed message
echo "💾 Committing changes..."
git commit -m "Fix: Replace lock timeout sys.exit calls with fail-closed retry to prevent Railway infinite restart loops

CRITICAL FIXES:
- Line 1797: Lock acquisition timeout now retries instead of exiting
- Line 1832: Duplicate deployment now enters standby instead of exiting  
- Line 6259: Added startup completion marker for deployment visibility

PROBLEM ADDRESSED:
The bot was entering an infinite restart loop when:
- New deployment arrived before old deployment released Redis lock
- Redis temporarily unreachable during startup
- Multiple container replicas spinning up simultaneously

When lock acquisition failed, bot called sys.exit(1) immediately:
  Container starts → Lock fails → sys.exit(1) → Railway auto-restarts (5s)
  → Lock STILL held by previous deployment → sys.exit(1) → REPEAT ∞

SOLUTION:
Instead of crashing, bot now uses _enter_fail_closed_standby():
  Container starts → Lock fails → Retry with backoff (15s intervals)
  → Old lock TTL expires or heartbeat stops → New lock acquired ✅
  → Bot initializes normally → System stable ✅

RETRYABLE CONFIGURATION:
  NIJA_FAIL_CLOSED_RETRY_INTERVAL_S=15 (sleep between retries)
  NIJA_FAIL_CLOSED_MAX_REDIS_FAILURES=5 (max retry attempts)

Can be tuned higher for Railway if needed:
  NIJA_FAIL_CLOSED_MAX_REDIS_FAILURES=20

TESTING:
After deploy, watch for:
  ✅ '🚀 BOT FULLY STARTED - ENTERING MAIN LOOP' (bot ready)
  ✅ Connection should be stable without repeated restarts
  ❌ Should NOT see sys.exit(1) followed by container restart"

# Push to origin
echo "🔄 Pushing to main branch..."
git push origin main

echo ""
echo "✅ Deploy complete!"
echo ""
echo "Next steps:"
echo "1. Go to Railway dashboard → Bot service"
echo "2. Trigger manual deploy or wait for auto-deploy"
echo "3. Monitor logs for '🚀 BOT FULLY STARTED' marker"
