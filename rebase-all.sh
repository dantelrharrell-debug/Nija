#!/bin/bash

# --- Step 0: Save uncommitted changes ---
echo "🔹 Stashing any uncommitted changes..."
git stash push -m "backup-before-sync"

# --- Step 1: Update main branch ---
echo "🔹 Checking out main and pulling latest changes..."
git checkout main || { echo "❌ Failed to checkout main"; exit 1; }
git fetch origin
git reset --hard origin/main
echo "✅ Main branch is up to date."

# --- Step 2: Rebase all local branches onto main ---
for branch in $(git for-each-ref --format='%(refname:short)' refs/heads/ | grep -v '^main$'); do
    echo "🔹 Rebasing branch '$branch' onto main..."
    git checkout "$branch" || { echo "❌ Failed to checkout $branch"; continue; }
    git fetch origin
    git rebase main
    if [ $? -ne 0 ]; then
        echo "⚠️ Rebase conflict detected in $branch! Skipping this branch for now."
        echo "💡 To fix later, checkout $branch and run: git rebase --continue or git rebase --abort"
        git rebase --abort
        continue
    fi
    echo "🔹 Force-pushing rebased branch '$branch' to origin..."
    git push --force-with-lease origin "$branch"
done

# --- Step 3: Return to main and restore stashed changes ---
git checkout main
if git stash list | grep -q "backup-before-sync"; then
    echo "🔹 Restoring stashed changes..."
    git stash pop
fi

echo "✅ All local branches rebased where possible. Conflicted branches skipped; check logs above."
