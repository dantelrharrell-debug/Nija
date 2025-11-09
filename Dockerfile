# Base image
FROM python:3.11-slim

# Set workdir
WORKDIR /app

# Copy app code
COPY . /app

# Upgrade pip
RUN pip install --upgrade pip

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port for Flask/Gunicorn
EXPOSE 5000

# Start your advanced bot
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "start_nija_advanced_safe:app"]
