# Dockerfile.debug
FROM python:3.11-slim  # You can also change this to 3.10-slim if that's the last working

WORKDIR /app

# Copy all project files
COPY . .

# Upgrade pip and install dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Optional environment variables
ENV LOG_LEVEL=INFO
ENV PYTHONUNBUFFERED=1

# Keep container alive for debugging
CMD ["tail", "-f", "/dev/null"]
