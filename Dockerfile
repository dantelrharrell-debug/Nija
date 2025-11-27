# Use slim Python 3.11 base
FROM python:3.11-slim

# Install system dependencies needed for pip and git installs
RUN apt-get update \
 && apt-get install -y --no-install-recommends git build-essential gcc libffi-dev musl-dev \
 && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
 && python -m pip install --no-cache-dir -r /app/requirements.txt

# Copy app code
COPY . /app

# Expose port for Flask/Gunicorn
EXPOSE 5000

# Use python -m gunicorn (robust way to run gunicorn)
CMD ["python", "-m", "gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--workers", "2"]
