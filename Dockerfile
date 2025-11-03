# Use a stable Python slim image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy requirements first (cache layer)
COPY requirements.txt .

# Upgrade pip and install dependencies
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of your project
COPY . .

# Expose the port Railway sets
ENV PORT 10000

# Command to run the Flask app
CMD ["gunicorn", "nija_bootstrap:app", "--workers", "1", "--bind", "0.0.0.0:10000"]
