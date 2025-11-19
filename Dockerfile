FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies for crypto libraries
RUN apt-get update && apt-get install -y \
    build-essential \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages globally
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY . .

# Expose port for Railway
ENV PORT=5000
EXPOSE $PORT

# Start the app with Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "main:app", "--workers=1", "--threads=2"]
