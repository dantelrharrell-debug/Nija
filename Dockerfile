# Use Python 3.12 slim
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy poetry / pyproject / source files
COPY pyproject.toml poetry.lock* /app/
COPY src /app/src

# Set environment variables
ENV PYTHONPATH=/app/src
ENV FLASK_APP=src.wsgi

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && pip install --upgrade pip setuptools wheel \
    && pip install "poetry>=1.7.0" \
    && poetry install --no-root --no-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Expose port
EXPOSE 5000

# Start app via Gunicorn
CMD ["gunicorn", "-c", "gunicorn.conf.py", "src.wsgi:app"]
