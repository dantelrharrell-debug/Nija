# -------------------------------
# Base image
# -------------------------------
FROM python:3.11-slim

# -------------------------------
# Set working directory
# -------------------------------
WORKDIR /usr/src/app

# -------------------------------
# System dependencies
# -------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        build-essential \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# -------------------------------
# Upgrade pip & core Python tools
# -------------------------------
RUN python3 -m pip install --upgrade pip setuptools wheel

# -------------------------------
# Copy requirements and install
# -------------------------------
COPY requirements.txt .

# Fix any potential merge conflict markers before installing
RUN sed -i '/^<<<<<<< HEAD$/,/^>>>>>>>/d' requirements.txt

RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# -------------------------------
# Install additional Python packages
# -------------------------------
RUN pip install --no-cache-dir python-dotenv flask gunicorn

# -------------------------------
# Copy application code
# -------------------------------
COPY . .

# -------------------------------
# Make entrypoint executable
# -------------------------------
RUN chmod +x ./entrypoint.sh

# -------------------------------
# Expose port for Gunicorn
# -------------------------------
EXPOSE 8080

# -------------------------------
# Command to run the app with Gunicorn
# -------------------------------
CMD ["gunicorn", "wsgi:app", "-c", "gunicorn.conf.py"]
