# --- Base image ---
FROM python:3.11-slim

# --- Set working directory ---
WORKDIR /app

# --- Copy dependencies ---
COPY requirements.txt /app/

# --- System dependencies for building some packages ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# --- Upgrade pip and install Python dependencies ---
RUN pip install --upgrade pip
RUN pip install -r /app/requirements.txt

# --- Copy application code ---
COPY . /app

# --- Default command ---
# Lists files for debug, then runs main.py and keeps container alive
CMD ["sh", "-c", "ls -la /app; python -u /app/main.py"]
