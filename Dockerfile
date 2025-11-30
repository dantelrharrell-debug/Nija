# ---------- Base Image ----------
FROM python:3.11-slim

# ---------- Set working directory ----------
WORKDIR /app

# ---------- Install system dependencies ----------
# git is needed to install some Python packages from GitHub
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# ---------- Install Python dependencies ----------
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# ---------- Copy application ----------
COPY . .

# ---------- Expose port ----------
ENV PORT=8080
EXPOSE ${PORT}

# ---------- Start Gunicorn ----------
CMD ["sh", "-c", "exec gunicorn wsgi:app \
  --bind 0.0.0.0:${PORT:-8080} \
  --workers 2 \
  --worker-class gthread \
  --threads 1 \
  --timeout 120 \
  --graceful-timeout 120 \
  --log-level debug \
  --capture-output \
  --enable-stdio-inheritance \
  -c ''"]
