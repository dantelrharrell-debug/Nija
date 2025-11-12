# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Copy entire app directory (preserves your current layout)
COPY app/ ./app/
COPY requirements.txt ./

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the package module (safe relative import as package)
CMD ["python3", "-m", "app.start_bot_main"]
