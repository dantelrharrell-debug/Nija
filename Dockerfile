# Use official Python base image
FROM python:3.11-slim

# Set work directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Install dependencies once
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir gunicorn

# Copy app code
COPY . .

# Expose port
EXPOSE 5000

# Start Flask app using Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "web.wsgi:app"]
