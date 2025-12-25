#!/bin/bash
git config user.email "dantelrharrell@users.noreply.github.com"
git config user.name "dantelrharrell-debug" 
git config commit.gpgsign false
git add -A
git commit -m "Fix API rate limiting and volume filters" || echo "Nothing to commit or commit failed"
git push origin main
echo "Done!"
