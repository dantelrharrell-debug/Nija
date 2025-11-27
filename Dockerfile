# ----------------------
# Dockerfile for Nija Trading Bot
# ----------------------
# Use official Python 3.11 slim image
FROM python:3.11-slim

# ----------------------
# ENV VARIABLES (Set API keys in container runtime or .env)
# ----------------------
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

# ----------------------
# WORKDIR
# ----------------------
WORKDIR /app

# ----------------------
# COPY FILES
# ----------------------
COPY requirements.txt .
COPY app.py .
COPY nija_client.py .

# ----------------------
# INSTALL DEPENDENCIES
# ----------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libssl-dev \
        libffi-dev \
        python3-dev \
        curl \
    && pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ----------------------
# EXPOSE PORT
# ----------------------
EXPOSE 5000

# ----------------------
# ENTRYPOINT
# ----------------------
# Use Gunicorn with 2 workers and gthread (threaded) for Flask + background trading thread
CMD ["gunicorn", "-w", "2", "-k", "gthread", "--threads", "2", "-b", "0.0.0.0:5000", "app:app"]
