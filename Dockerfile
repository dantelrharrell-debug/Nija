# ===============================
# NIJA Trading Bot – Dockerfile
# ===============================

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy project files
COPY . .

# -------------------------------
#   Gunicorn / Port Configuration
# -------------------------------
ENV PORT=8080
EXPOSE 8080

# Run Gunicorn (Railway-friendly)
CMD ["sh", "-c", "exec gunicorn wsgi:app \
  --bind 0.0.0.0:${PORT:-8080} \
  --workers 2 \
  --worker-class gthread \
  --threads 1 \
  --timeout 120 \
  --graceful-timeout 120 \
  --log-level debug \
  --capture-output \
  --enable-stdio-inheritance"]
