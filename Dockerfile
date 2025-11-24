# --- Base image ---
FROM python:3.11-slim

# --- Set working directory ---
WORKDIR /app

# --- Install system dependencies ---
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        build-essential \
        libssl-dev \
        libffi-dev \
        python3-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# --- Copy requirements file ---
COPY requirements.txt .

# --- Upgrade pip and install Python dependencies ---
RUN pip install --no-cache-dir --upgrade pip==25.3 \
    && pip install --no-cache-dir -r requirements.txt

# --- Copy app source code ---
COPY . .

# --- Make start script executable ---
RUN chmod +x /app/start_all.sh

# --- Expose port if needed (adjust if your app uses a different port) ---
EXPOSE 5000

# --- Run the start script ---
CMD ["/app/start_all.sh"]
