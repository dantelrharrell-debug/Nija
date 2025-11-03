# Use Python 3.10-slim for maximum compatibility
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Upgrade pip and install dependencies
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy all project files
COPY . .

# Set environment variables Railway can override
ENV PORT=10000
ENV LOG_LEVEL=INFO

# Expose port
EXPOSE 10000

# Command to run Gunicorn with your bootstrap file
CMD ["gunicorn", "nija_bootstrap:app", "--workers", "1", "--bind", "0.0.0.0:10000"]
