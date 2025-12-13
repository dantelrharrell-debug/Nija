#!/bin/bash
cd /workspaces/Nija
git add bot/broker_manager.py bot.py
git commit -m "Add preflight credential checklist, stricter PEM validation (require BEGIN/END headers)"
git push origin main
