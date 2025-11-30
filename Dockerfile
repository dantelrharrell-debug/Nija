# Use Python 3.11 slim
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH="/app:/bot:$PYTHONPATH"

# Install system deps for building wheels
RUN apt-get update && \
    apt-get install -y --no-install-recommends git build-essential && \
    rm -rf /var/lib/apt/lists/*

# Copy project files first so pip cache works
COPY requirements.txt .
# Install dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy entire repo
COPY . /app

# Install vendored coinbase packages under /app/cd/vendor
# We install both wrapper and implementation as editable if possible
RUN pip install --no-deps -e ./cd/vendor/coinbase_advanced || true
RUN pip install --no-deps -e ./cd/vendor/coinbase_advanced_py || true

# Make entrypoint executable
RUN chmod +x ./entrypoint.sh

EXPOSE 5000

ENTRYPOINT ["./entrypoint.sh"]
