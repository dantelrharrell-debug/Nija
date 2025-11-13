# --- rest of Dockerfile above ---
CMD ["sh", "-lc", "ls -la /app || true; python -u main.py || python -u app/main.py || tail -f /tmp/nija_started.ok"]
