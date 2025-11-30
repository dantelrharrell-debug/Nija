# Use slim Python 3.11 image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY . .

# Make Python see top-level folders like 'bot'
ENV PYTHONPATH=/app

# Expose port
EXPOSE 5000

# Start Gunicorn
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
