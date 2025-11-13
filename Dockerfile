# --- Base image ---
FROM python:3.11-slim

# --- Set working directory ---
WORKDIR /app

# --- Install system dependencies ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# --- Copy project files ---
COPY . /app

# --- Upgrade pip ---
RUN pip install --upgrade pip

# --- Install Python dependencies ---
RUN pip install -r /app/requirements.txt

# --- Set default command ---
# This checks both /app and root for main.py and keeps container alive
CMD ["sh", "-c", "ls -la /app; ls -la .; python -u /app/main.py || python -u main.py || tail -f /tmp/nija_started.ok"]
