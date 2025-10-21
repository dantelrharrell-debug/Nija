# Base image
FROM mcr.microsoft.com/devcontainers/python:3.11

# Set working directory
WORKDIR /app

# Copy project files
COPY . /app

# Install dependencies
RUN pip install --upgrade pip setuptools wheel
RUN pip install -r requirements.txt

# Expose bot port
EXPOSE 5000

# Run bot
CMD ["python", "nija_bot_web.py"]
