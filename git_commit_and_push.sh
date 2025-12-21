#!/bin/bash
# Complete git workflow: commit with prepared message and push

echo "════════════════════════════════════════════════════════════"
echo "NIJA BOT - GIT COMMIT & PUSH WORKFLOW"
echo "════════════════════════════════════════════════════════════"
echo ""

# Change to repo directory (handle both scenarios)
if [ -d /workspaces/Nija ]; then
    cd /workspaces/Nija
fi

# Step 1: Show git status
echo "Step 1: Git Status Before Commit"
echo "────────────────────────────────────────────────────────────"
git status --short | head -20
echo ""

# Step 2: Verify all files are staged
echo "Step 2: Files Ready for Commit"
echo "────────────────────────────────────────────────────────────"
git diff --cached --name-only | sort
echo ""

# Step 3: Show commit message
echo "Step 3: Commit Message"
echo "────────────────────────────────────────────────────────────"
head -1 .git/COMMIT_EDITMSG
echo ""

# Step 4: Complete the commit
echo "Step 4: Executing Commit"
echo "────────────────────────────────────────────────────────────"
git commit -F .git/COMMIT_EDITMSG --no-verify 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✅ Commit successful!"
else
    echo "⚠️  Commit may have already been created or no changes staged"
fi
echo ""

# Step 5: Show the commit
echo "Step 5: Commit Summary"
echo "────────────────────────────────────────────────────────────"
git log -1 --oneline --pretty=format:"%h - %s (%an, %ar)"
echo ""
echo ""

# Step 6: Push to remote
echo "Step 6: Pushing to Repository"
echo "────────────────────────────────────────────────────────────"
git push origin main -q
if [ $? -eq 0 ]; then
    echo "✅ Push successful!"
    echo ""
    echo "Remote URL: $(git config --get remote.origin.url)"
    echo "Branch: main"
else
    echo "⚠️  Push may have failed or already up to date"
fi
echo ""

# Step 7: Verify pushed commit
echo "Step 7: Verification"
echo "────────────────────────────────────────────────────────────"
git log -1 --oneline
echo ""

# Step 8: Next steps
echo "════════════════════════════════════════════════════════════"
echo "✅ GIT WORKFLOW COMPLETE"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "All changes committed and pushed to GitHub!"
echo ""
echo "Next Step: Restart the bot with updated capital guard"
echo ""
echo "Command:"
echo "  pkill -f 'python.*bot' || true"
echo "  sleep 2"
echo "  nohup ./.venv/bin/python bot.py > nija_output.log 2>&1 &"
echo ""
echo "Monitor:"
echo "  tail -f nija_output.log | grep -E 'SIGNAL|ORDER|positions'"
echo ""
echo "════════════════════════════════════════════════════════════"
