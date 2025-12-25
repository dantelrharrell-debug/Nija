#!/bin/bash
cd /workspaces/Nija
git add -A
git commit -m "Fix Render deployment - update start.sh, add render.yaml, portfolio diagnostics"
git push origin main
echo "✅ Changes pushed to GitHub"
