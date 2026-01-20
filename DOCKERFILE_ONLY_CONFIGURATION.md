# Dockerfile-Only Configuration

**Date**: January 20, 2026  
**Issue**: Railway detecting Dockerfile instead of using explicit configuration  
**Solution**: Removed `nixpacks.toml` to ensure Railway uses Dockerfile exclusively

---

## Background

This repository is configured to use **Dockerfile** for builds on Railway (via `railway.json`), not NIXPACKS. This is critical because:

1. **Kraken SDK Installation**: The Dockerfile includes explicit installation and verification of `krakenex` and `pykrakenapi` libraries
2. **Build Reliability**: Docker builds are reproducible and include preflight checks
3. **Fail-Fast Behavior**: If dependencies fail to install, the build stops immediately (preventing broken deployments)

---

## The Problem

Railway's auto-detection was showing:
```
Using Detected Dockerfile
```

This indicates Railway was **detecting** the Dockerfile rather than using it because it was **explicitly configured** in `railway.json`.

The presence of `nixpacks.toml` file in the repository caused this behavior. Even though `railway.json` specified `"builder": "DOCKERFILE"`, Railway's auto-detection logic would sometimes prefer or fall back to NIXPACKS.

---

## The Fix

**Removed**: `nixpacks.toml` file  
**Updated**: Added `nixpacks.toml` to `.gitignore` to prevent re-addition  
**Result**: Railway will now use the Dockerfile as explicitly configured in `railway.json`

### Railway Configuration (railway.json)
```json
{
  "build": {
    "builder": "DOCKERFILE",
    "buildEnvironment": "V3"
  }
}
```

This configuration tells Railway to:
- Use the Dockerfile (not NIXPACKS)
- Use build environment V3
- Ignore any auto-detection logic

---

## Why NIXPACKS Was Problematic

### NIXPACKS Behavior
```toml
[phases.install]
cmds = [
  'python3 -m pip install --upgrade pip setuptools wheel',
  'python3 -m pip install -r requirements.txt'
]
```

**Issues**:
- Packages install in arbitrary order
- Version conflicts may occur silently
- No verification of critical dependencies
- Errors may not be visible in logs
- Kraken SDK installation sometimes fails silently

### Dockerfile Behavior
```dockerfile
# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .
```

**Benefits**:
- Controlled installation order
- Explicit version pinning via `requirements.txt`
- Build fails immediately if any package fails to install
- Clear error messages in build logs
- Kraken SDK verified during startup via `start.sh`

---

## Verification

### Expected Build Logs (After Fix)

Railway should now show:
```
Building with Dockerfile
[1/5] FROM docker.io/library/python:3.11-slim
[2/5] WORKDIR /app
[3/5] COPY requirements.txt .
[4/5] RUN pip install --no-cache-dir -r requirements.txt
[5/5] COPY . .
```

**Not**: "Using Detected Dockerfile" (which indicates auto-detection)  
**But**: "Building with Dockerfile" (which indicates explicit configuration)

### Startup Verification

The `start.sh` script includes checks for Kraken SDK:
```bash
# Test Kraken module
if [ -n "${KRAKEN_MASTER_API_KEY}" ] && [ -n "${KRAKEN_MASTER_API_SECRET}" ]; then
    $PY -c "import krakenex; import pykrakenapi; print('✅ Kraken SDK available')" || {
        echo "❌ CRITICAL: Kraken SDK is NOT installed"
        exit 1
    }
fi
```

Expected output:
```
✅ Kraken SDK (krakenex + pykrakenapi) available
```

---

## Related Documentation

- **SOLUTION_KRAKEN_LIBRARY_NOT_INSTALLED.md** - Original issue with NIXPACKS silently failing to install Kraken SDK
- **DOCKER_DEPLOYMENT_GUIDE.md** - General Docker deployment documentation
- **RAILWAY_MVP_CHECKLIST.md** - Railway deployment checklist

---

## Important Notes

### Do Not Re-Add nixpacks.toml

The `nixpacks.toml` file has been:
1. Removed from the repository
2. Added to `.gitignore` 

**Do not re-add this file**. It causes Railway to potentially use NIXPACKS instead of or alongside the Dockerfile, which can lead to:
- Silent installation failures
- Inconsistent builds
- Missing Kraken SDK
- Broken deployments

### Railway Configuration is Final

The `railway.json` file explicitly configures:
```json
{
  "build": {
    "builder": "DOCKERFILE"
  }
}
```

This is the **only** build configuration that should be used. Any alternative build methods (NIXPACKS, Buildpacks, etc.) should not be configured.

### If You See "Detected Dockerfile" Again

If Railway deployment logs show "Using Detected Dockerfile" instead of "Building with Dockerfile":

1. **Check for nixpacks.toml**: Ensure it hasn't been re-added
2. **Verify railway.json**: Confirm `"builder": "DOCKERFILE"` is present
3. **Clear Railway cache**: Delete and recreate the Railway service
4. **Contact Railway support**: If the issue persists after above steps

---

## Summary

| Component | Status | Notes |
|-----------|--------|-------|
| `Dockerfile` | ✅ Present | Used for all builds |
| `railway.json` | ✅ Configured | Explicit `"builder": "DOCKERFILE"` |
| `nixpacks.toml` | ✅ Removed | Prevented auto-detection conflicts |
| `.gitignore` | ✅ Updated | Prevents re-adding nixpacks.toml |
| Kraken SDK | ✅ Verified | Checked during startup |

**Result**: Railway will now exclusively use the Dockerfile for all builds, ensuring reliable and reproducible deployments with proper Kraken SDK installation.
