#!/bin/bash
set -euo pipefail

echo "🔹 Stashing any uncommitted changes..."
git stash push -m "backup-before-sync" || true

echo "🔹 Updating main branch..."
git fetch origin main:main
git checkout main
git reset --hard origin/main
echo "✅ Main branch is up to date."

# Rebase all local branches onto main
for branch in $(git for-each-ref --format='%(refname:short)' refs/heads/ | grep -v '^main$'); do
    echo "🔹 Processing branch '$branch'..."
    git checkout "$branch"

    # Attempt rebase
    if git rebase main; then
        echo "✅ Branch '$branch' rebased successfully. Force-pushing..."
        git push --force-with-lease origin "$branch"
    else
        echo "⚠️ Rebase conflict in '$branch'. Aborting rebase and skipping branch."
        git rebase --abort
        continue
    fi
done

# Return to main branch and restore stashed changes
git checkout main
if git stash list | grep -q "backup-before-sync"; then
    echo "🔹 Restoring stashed changes..."
    git stash pop || true
fi

echo "✅ All branches processed. Conflicted branches skipped automatically."
