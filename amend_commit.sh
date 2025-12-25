#!/bin/bash
cd /workspaces/Nija
git commit --amend -m "Add preflight credential checklist, stricter PEM validation (require BEGIN/END headers)

- Broker: Validate PEM content requires BEGIN/END headers; ignore empty/malformed PEM
- Broker: Fall back to JWT (API_KEY+SECRET) when PEM is missing or invalid
- Bot: Display clear credential checklist on broker connection failure instead of silent crash loop
- Bot: Exit cleanly with actionable setup instructions for Railway deployment

Fixes repeated crash loops when COINBASE_PEM_PATH is set but file doesn't exist and no valid JWT credentials are present."
git push --force-with-lease origin main
