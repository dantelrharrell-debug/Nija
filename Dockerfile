# --- Step 1: Base image ---
FROM python:3.11-slim

# --- Step 2: Set environment variables ---
# GITHUB_PAT will be set in Railway environment variables
ENV PATH="/root/.local/bin:$PATH"

# --- Step 3: Install system dependencies ---
RUN apt-get update && \
    apt-get install -y --no-install-recommends git build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# --- Step 4: Copy requirements if you have them ---
# COPY requirements.txt /app/requirements.txt

# --- Step 5: Install Python dependencies ---
# If you have a requirements.txt
# RUN pip install --upgrade pip && pip install -r /app/requirements.txt

# --- Step 6: Install your private GitHub package securely ---
RUN pip install --upgrade pip
RUN pip install git+https://$GITHUB_PAT@github.com/dantelrharrell-debug/coinbase_advanced_py.git@main#egg=coinbase_advanced_py

# --- Step 7: Copy your bot code ---
COPY . /app
WORKDIR /app

# --- Step 8: Expose port (Railway detects automatically) ---
EXPOSE 8080

# --- Step 9: Run your bot ---
CMD ["python", "bot/live_trading.py"]
