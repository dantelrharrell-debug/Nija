# Base image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy project files
COPY . /app

# Install dependencies
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

# Set Python path for your src folder
ENV PYTHONPATH=/app/src

# Expose port
EXPOSE 5000

# Start Gunicorn directly
CMD ["gunicorn", "-c", "gunicorn.conf.py", "src.wsgi:app"]
