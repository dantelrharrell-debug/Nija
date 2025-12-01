FROM python:3.11-slim
WORKDIR /usr/src/app

# Install git (for future extensibility, not strictly required by PyPI install)
RUN apt-get update && \
    apt-get install -y git && \
    rm -rf /var/lib/apt/lists/*

# Upgrade pip and install requirements
COPY requirements.txt .
RUN python3 -m pip install --upgrade pip
RUN python3 -m pip install --no-cache-dir -r requirements.txt

# Install coinbase-advanced-py from PyPI (recommended)
RUN python3 -m pip install --no-cache-dir coinbase-advanced-py

# Copy app code
COPY . .

EXPOSE 5000

CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
