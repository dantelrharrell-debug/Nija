# Use Python 3.11 slim base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Upgrade pip and install requirements
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Set port from environment variable (Railway provides $PORT)
ENV PORT=5000
EXPOSE $PORT

# Start app with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "main:app", "--workers=1", "--threads=2"]
