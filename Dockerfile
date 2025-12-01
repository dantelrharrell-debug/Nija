FROM python:3.11-slim
WORKDIR /usr/src/app

# Install git (if needed by other deps) and build tools
RUN apt-get update && \
    apt-get install -y git && \
    rm -rf /var/lib/apt/lists/*

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install official coinbase‑advanced‑py from PyPI
RUN pip install --no-cache-dir coinbase-advanced-py

# Copy application code
COPY . .

EXPOSE 5000

# Start Gunicorn
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
