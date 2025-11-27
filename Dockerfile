FROM python:3.11-slim

# Install system build deps and git
RUN apt-get update \
 && apt-get install -y --no-install-recommends git build-essential gcc libffi-dev musl-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
 && python -m pip install --no-cache-dir -r /app/requirements.txt

# Copy app code
COPY . /app

# Expose port
EXPOSE 5000

# Use python -m gunicorn (more robust than relying on PATH binary)
CMD ["python", "-m", "gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--workers", "2"]
