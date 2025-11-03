# -----------------------------
# Dockerfile for Railway + Nija
# -----------------------------

# Base image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy only requirements first (cache layer)
COPY requirements.txt .

# Upgrade pip and install dependencies
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the rest of your code
COPY . .

# Set environment variables (Railway can override)
ENV LOG_LEVEL=INFO
ENV PYTHONUNBUFFERED=1

# Expose port (Gunicorn binds here)
EXPOSE 10000

# Start Nija with Gunicorn
CMD ["gunicorn", "nija_bootstrap:app", "--workers", "1", "--bind", "0.0.0.0:10000"]
