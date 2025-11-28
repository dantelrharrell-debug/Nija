FROM python:3.11-slim

# Put app files into /app
WORKDIR /app

# Install system deps that pip sometimes needs
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (if you use a requirements.txt). If you don't have one,
# adapt this step in your host UI to add packages.
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

# Ensure entrypoint is executable
RUN chmod +x /app/start_all.sh

ENTRYPOINT ["/app/start_all.sh"]
