# ===========================
# Dockerfile for NIJA Trading Bot
# ===========================

FROM python:3.11-slim

# Install git and minimal build tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      git \
      build-essential \
      gcc \
      libssl-dev \
      libffi-dev \
      ca-certificates \
      curl && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /usr/src/app

# Copy project files
COPY . /usr/src/app

# Upgrade pip, setuptools, wheel
RUN pip install --no-cache-dir -U pip setuptools wheel

# Install Python dependencies
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# Expose Gunicorn port
EXPOSE 5000

# Use a proper Gunicorn CMD
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
