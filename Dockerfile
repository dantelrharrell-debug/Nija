FROM python:3.11-slim

# Install system build deps needed for some packages
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    libssl-dev \
    libffi-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Upgrade pip and install Python deps
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY . .

ENV PORT=5000
EXPOSE 5000

# Default command (Procfile on Railway will override if present)
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "main:app"]
