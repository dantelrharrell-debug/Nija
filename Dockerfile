# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy all files
COPY . /app

# Upgrade pip and install dependencies
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install gunicorn

# Expose the port for Flask
EXPOSE 5000

# Command to run the app
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "web_service:app"]
