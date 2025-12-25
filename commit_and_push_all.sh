#!/bin/bash
git config user.email "dantelrharrell@users.noreply.github.com"
git config user.name "dantelrharrell-debug"  
git config commit.gpgsign false
git add -A
git commit -m "Cleanup: Add verification helper scripts" || true
git push origin main
