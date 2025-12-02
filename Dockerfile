# Use official Python slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Copy application code
COPY . .

# Upgrade pip
RUN pip install --upgrade pip

# Install standard dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install coinbase_advanced_py directly from GitHub
RUN pip install --no-cache-dir git+https://github.com/coinbase/coinbase-advanced-py.git@d316b758811ce3c13ef179fb228c569b333cddd1#egg=coinbase_advanced_py

# Expose port for Gunicorn
EXPOSE 5000

# Start Gunicorn with your config
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
