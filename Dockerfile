# Use official Python 3.11 image
FROM python:3.11-slim

# Set working directory in container
WORKDIR /usr/src/app

# Set Python path so 'web' and 'bot' are recognized
ENV PYTHONPATH=/usr/src/app

# Copy dependency file first (for caching)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Expose port
EXPOSE 8080

# Start Gunicorn server for your web app
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8080", "web:app"]
