# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential gcc libffi-dev musl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt /app/requirements.txt

# Upgrade pip, setuptools, wheel and install Python deps
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir -r /app/requirements.txt

# Copy the rest of your app
COPY . /app

# Optional: verify Coinbase import
RUN python - <<'END'
try:
    from coinbase_advanced.client import Client
    print("Coinbase import OK ✅")
except Exception as e:
    print("Coinbase import FAILED ❌", e)
END

# Expose the port your app runs on
EXPOSE 5000

# Start app via Gunicorn
CMD ["python", "-m", "gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--workers", "2"]
