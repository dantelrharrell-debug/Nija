# Use official Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy bot code
COPY . /app

# Install dependencies
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install gunicorn \
    && pip install coinbase-advanced

# Expose port for web server
EXPOSE 8080

# Set environment variables (if not using a .env)
ENV FLASK_ENV=production
ENV COINBASE_API_KEY=${COINBASE_API_KEY}
ENV COINBASE_API_SECRET=${COINBASE_API_SECRET}

# Use a startup script to start Gunicorn (no Flask dev server)
CMD ["./start_all.sh"]
