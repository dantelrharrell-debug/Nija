# Railway Build Configuration Guide

## Git Metadata Injection

NIJA automatically injects Git metadata (branch, commit hash, build timestamp) into the application during the Docker build process. This information is used for version tracking and debugging.

## How It Works

### Automatic Railway Integration

Railway automatically provides Git metadata as build arguments during the Docker build. Our Dockerfile accepts these build arguments:

```dockerfile
ARG GIT_BRANCH=unknown
ARG GIT_COMMIT=unknown
ARG BUILD_TIMESTAMP=unknown
```

### Railway's Default Build Arguments

Railway automatically sets these build arguments based on the Git repository:
- `RAILWAY_GIT_BRANCH` - The Git branch being deployed
- `RAILWAY_GIT_COMMIT_SHA` - The full commit SHA
- `RAILWAY_GIT_COMMIT_MESSAGE` - The commit message

### Manual Configuration (Optional)

If you need to manually set build arguments in Railway, you can do so in the `railway.json` file:

```json
{
  "build": {
    "builder": "DOCKERFILE",
    "buildEnvironment": "V3",
    "dockerfilePath": "Dockerfile",
    "buildArgs": {
      "GIT_BRANCH": "$RAILWAY_GIT_BRANCH",
      "GIT_COMMIT": "$RAILWAY_GIT_COMMIT_SHA",
      "BUILD_TIMESTAMP": "$RAILWAY_DEPLOYMENT_TIME"
    }
  }
}
```

**Note:** Railway V3 build environment should automatically pass these values, so manual configuration is usually not needed.

## Verification

After deployment, you can verify the Git metadata was injected correctly by checking the logs:

```
🔍 Injecting Git metadata...
Using GIT_BRANCH from build argument: main
Using GIT_COMMIT from build argument: abc123def456789
Using BUILD_TIMESTAMP from build argument: 2026-02-16T14:00:00Z
📋 Git Branch: main
📋 Git Commit: abc123d
📋 Build Time: 2026-02-16T14:00:00Z
✅ Version info generated: bot/version_info.py
```

If you see this message instead:
```
Warning: Could not inject git metadata (continuing anyway)
```

This means the build arguments were not provided. The application will still work but will show "unknown" for Git metadata.

## For Local Development

When building locally with Docker, you can manually provide build arguments:

```bash
docker build \
  --build-arg GIT_BRANCH="$(git rev-parse --abbrev-ref HEAD)" \
  --build-arg GIT_COMMIT="$(git rev-parse HEAD)" \
  --build-arg BUILD_TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
  -t nija .
```

Or use a simpler approach for testing:

```bash
docker build \
  --build-arg GIT_BRANCH="main" \
  --build-arg GIT_COMMIT="local-build" \
  --build-arg BUILD_TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
  -t nija .
```

## Fallback Behavior

The `inject_git_metadata.sh` script has intelligent fallback behavior:

1. **First Priority:** Use build arguments if provided (for Docker builds without .git)
2. **Second Priority:** Use `git` commands if .git directory is available (for local dev)
3. **Last Resort:** Use "unknown" as default values

This ensures the build always succeeds, even if Git metadata is unavailable.

## Files Generated

The metadata injection creates:
- `bot/version_info.py` - Python module with version information
- `.env.build` - Environment variables for runtime use (optional)

Both files are auto-generated and should not be edited manually.

## Security Considerations

- The `.git` directory is excluded from the Docker image via `.dockerignore` to reduce image size and improve security
- Git metadata is captured at build time, not runtime
- No sensitive information (API keys, secrets) should ever be in Git metadata

## Troubleshooting

### Issue: Build shows "unknown" for Git metadata

**Cause:** Build arguments not passed to Docker build

**Solution:** 
1. Check that Railway is using build environment V3
2. Verify `railway.json` has correct configuration
3. Redeploy to trigger a fresh build

### Issue: Script fails during Docker build

**Cause:** Script permissions or syntax error

**Solution:**
1. Verify `inject_git_metadata.sh` is executable: `chmod +x inject_git_metadata.sh`
2. Check script syntax: `bash -n inject_git_metadata.sh`
3. The build has a fallback and should continue even if metadata injection fails
