FROM python:3.11-slim

WORKDIR /usr/src/app

# Install only needed packages and clean up in one layer
RUN apt-get update && \
    apt-get install -y --no-install-recommends git build-essential && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies first to leverage caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY . .

EXPOSE 5000

# Run Gunicorn
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
