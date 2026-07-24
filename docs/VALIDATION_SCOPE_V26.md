# Validation scope

Focused checks compile the launcher, patcher, v22/v24 startup modules, and Render shell entrypoint; verify `start.sh` is rewritten idempotently; assert direct `main.py` launch is removed; and confirm late installation fails closed.
