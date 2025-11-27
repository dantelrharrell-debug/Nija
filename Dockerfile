# ----------------------
# Dockerfile for Nija Trading Bot
# ----------------------
FROM python:3.11-slim

# ----------------------
# ENV VARIABLES
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
COPY start_all.sh .

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
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ----------------------
# EXPOSE PORT
# ----------------------
EXPOSE 5000

# ----------------------
# START ALL SCRIPT
# ----------------------
CMD ["./start_all.sh"]
