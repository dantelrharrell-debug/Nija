#!/bin/bash
cd /workspaces/Nija
git add bot/broker_manager.py
git commit -m "Add detailed JWT credential validation and 401 error troubleshooting

- Add credential format validation (API Key should start with 'organizations/')
- Add API Secret length check (should be 128+ chars)
- Provide detailed 401 Unauthorized error diagnostics
- Give users 4-point fix guide for authentication errors
- Help users identify credential format issues vs invalid credentials"
git push --force-with-lease
