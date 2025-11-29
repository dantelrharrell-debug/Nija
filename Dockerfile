# Dockerfile - NIJA Bot (Railway-friendly) - Option A
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV PORT=8080

WORKDIR /app

# System deps for building cryptography/cffi
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential git ca-certificates dos2unix bash libffi-dev libssl-dev pkg-config \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy requirements first for cache
COPY requirements.txt /app/requirements.txt

# Upgrade pip & install Python deps
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy app and web (these must exist in repo)
COPY app/ /app/app/
COPY web/ /app/web/

# Optionally fetch bot at build-time if you set BOT_GIT_URL (build arg or env)
# If you don't set BOT_GIT_URL, no clone is attempted and build continues.
ARG BOT_GIT_URL=""
RUN if [ -n "$BOT_GIT_URL" ]; then \
      git clone --depth=1 "$BOT_GIT_URL" /app/bot || (echo "bot git clone failed" && false); \
    else \
      echo "No BOT_GIT_URL provided; skipping bot clone"; \
    fi

# Normalize any shell scripts if present
RUN if [ -f /app/scripts/start_all.sh ]; then dos2unix /app/scripts/start_all.sh && chmod +x /app/scripts/start_all.sh; fi
RUN if [ -f /app/start_all.sh ]; then dos2unix /app/start_all.sh && chmod +x /app/start_all.sh; fi

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "web.wsgi:application", \
     "--worker-class", "gthread", "--threads", "1", "--workers", "2", \
     "--log-level", "debug", "--capture-output"]
