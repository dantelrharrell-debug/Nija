# Use official slim Python 3.11 image
FROM python:3.11-slim

# Set work directory
WORKDIR /app

# Install system dependencies for building packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential gcc libffi-dev musl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .

# Upgrade pip/setuptools and install Python dependencies
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Expose port
EXPOSE 5000

# Start the app using Gunicorn
CMD ["python", "-m", "gunicorn", "app:app", "--bind", "0.0.0.0:5000", "--workers", "2"]
