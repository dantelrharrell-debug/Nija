#!/bin/bash
# Git Metadata Injection for NIJA Build
# Injects Git branch and commit information into version tracking

set -e

echo "🔍 Injecting Git metadata..."

# Get Git metadata - priority: explicit build args > Railway env vars > git commands
if [ -n "$GIT_BRANCH" ] && [ "$GIT_BRANCH" != "unknown" ]; then
    echo "Using GIT_BRANCH from build argument: $GIT_BRANCH"
elif [ -n "$RAILWAY_GIT_BRANCH" ]; then
    export GIT_BRANCH="$RAILWAY_GIT_BRANCH"
    echo "Using GIT_BRANCH from Railway environment: $GIT_BRANCH"
else
    export GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
fi

if [ -n "$GIT_COMMIT" ] && [ "$GIT_COMMIT" != "unknown" ]; then
    echo "Using GIT_COMMIT from build argument: $GIT_COMMIT"
    export GIT_COMMIT_SHORT="${GIT_COMMIT:0:7}"
elif [ -n "$RAILWAY_GIT_COMMIT_SHA" ]; then
    export GIT_COMMIT="$RAILWAY_GIT_COMMIT_SHA"
    export GIT_COMMIT_SHORT="${RAILWAY_GIT_COMMIT_SHA:0:7}"
    echo "Using GIT_COMMIT from Railway environment: $GIT_COMMIT_SHORT"
else
    export GIT_COMMIT=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
    export GIT_COMMIT_SHORT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
fi

if [ -n "$BUILD_TIMESTAMP" ] && [ "$BUILD_TIMESTAMP" != "unknown" ]; then
    echo "Using BUILD_TIMESTAMP from build argument: $BUILD_TIMESTAMP"
else
    export BUILD_TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
fi

echo "📋 Git Branch: $GIT_BRANCH"
echo "📋 Git Commit: $GIT_COMMIT_SHORT"
echo "📋 Build Time: $BUILD_TIMESTAMP"

# Create version file
cat > bot/version_info.py << EOF
"""
NIJA Version Information
Auto-generated during build process - DO NOT EDIT MANUALLY
"""

# Git metadata
GIT_BRANCH = "${GIT_BRANCH}"
GIT_COMMIT = "${GIT_COMMIT}"
GIT_COMMIT_SHORT = "${GIT_COMMIT_SHORT}"
BUILD_TIMESTAMP = "${BUILD_TIMESTAMP}"

# Version info
VERSION = "7.3.0"
RELEASE_NAME = "Autonomous Scaling Engine"

def get_version_string() -> str:
    """Get formatted version string with git info"""
    return f"NIJA v{VERSION} ({RELEASE_NAME}) - {GIT_BRANCH}@{GIT_COMMIT_SHORT}"

def get_full_version_info() -> dict:
    """Get complete version information"""
    return {
        'version': VERSION,
        'release_name': RELEASE_NAME,
        'git_branch': GIT_BRANCH,
        'git_commit': GIT_COMMIT,
        'git_commit_short': GIT_COMMIT_SHORT,
        'build_timestamp': BUILD_TIMESTAMP
    }
EOF

echo "✅ Version info generated: bot/version_info.py"

# Export for runtime use
echo "export GIT_BRANCH=$GIT_BRANCH" >> .env.build
echo "export GIT_COMMIT=$GIT_COMMIT" >> .env.build
echo "export GIT_COMMIT_SHORT=$GIT_COMMIT_SHORT" >> .env.build
echo "export BUILD_TIMESTAMP=$BUILD_TIMESTAMP" >> .env.build

echo "✅ Build environment variables saved to .env.build"
echo "🚀 Git metadata injection complete!"
