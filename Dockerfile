# Base image
FROM python:3.11-slim

WORKDIR /app

COPY . .

# Upgrade pip
RUN python3 -m pip install --upgrade pip

# Install Flask, Gunicorn, and other deps
RUN pip install --no-cache-dir Flask gunicorn

# Install coinbase_advanced directly from GitHub
RUN pip install --no-cache-dir git+https://github.com/coinbase/coinbase-advanced-py.git

# Expose Flask port
EXPOSE 5000

# Make start script executable
RUN chmod +x ./start_all.sh

CMD ["./start_all.sh"]
