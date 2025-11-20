# Use official Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Avoid root SSH issues and install git
RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Expose port (Flask default)
EXPOSE 5000

# Run the app via Gunicorn
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "main:app"]
