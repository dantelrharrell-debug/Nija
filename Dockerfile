# Dockerfile
FROM python:3.11-slim

# Create app directory
WORKDIR /app

# Install system deps for cryptography build wheels (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip
RUN pip install -r /app/requirements.txt

# Copy app
COPY . /app

# Expose webhook port
EXPOSE 8000

# Use environment variable PORT if present else default
ENV PORT=8000

# Entrypoint
CMD ["python", "start_bot.py"]
