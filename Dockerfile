# --- Step 1: Base image ---
FROM python:3.11-slim

# --- Step 2: Environment variables ---
# GITHUB_PAT is set in Railway, not hardcoded
ARG GITHUB_PAT
ENV PATH="/root/.local/bin:$PATH"
ENV GITHUB_PAT=${GITHUB_PAT}

# --- Step 3: Install system dependencies ---
RUN apt-get update && \
    apt-get install -y --no-install-recommends git build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# --- Step 4: Copy requirements ---
COPY requirements.txt /app/requirements.txt

# --- Step 5: Install Python dependencies ---
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt && \
    pip install --no-cache-dir git+https://${GITHUB_PAT}@github.com/dantelrharrell-debug/coinbase_advanced_py.git@main#egg=coinbase_advanced_py

# --- Step 6: Copy bot code ---
COPY . /app
WORKDIR /app

# --- Step 7: Expose port for Railway ---
EXPOSE 8080

# --- Step 8: Run bot ---
CMD ["python", "bot/live_trading.py"]
