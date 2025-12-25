#!/bin/bash
git config user.email "dantelrharrell@users.noreply.github.com"
git config user.name "dantelrharrell-debug" 
git config commit.gpgsign false
git push --force-with-lease origin main
echo "Done!"
