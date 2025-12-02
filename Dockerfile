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

# Remove any leftover merge conflict markers
RUN sed -i '/^<<<<<<< HEAD$/,/^>>>>>>>/d' requirements.txt

RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# Install essential Python packages
RUN pip install --no-cache-dir python-dotenv flask gunicorn

# -------------------------------
# Copy application code
# -------------------------------
COPY . .

# -------------------------------
# Copy entrypoint and make it executable
# -------------------------------
COPY entrypoint.sh /usr/src/app/entrypoint.sh
RUN chmod +x /usr/src/app/entrypoint.sh

# -------------------------------
# Expose port
# -------------------------------
EXPOSE 5000

# -------------------------------
# Entrypoint
# -------------------------------
ENTRYPOINT ["/usr/src/app/entrypoint.sh"]
