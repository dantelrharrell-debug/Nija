# --- Base image ---
FROM python:3.11-slim

# --- Set environment variables ---
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VIRTUALENVS_CREATE=false

# --- Install system dependencies ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# --- Set working directory ---
WORKDIR /app

# --- Copy requirements first for caching ---
COPY requirements.txt .

# --- Install Python dependencies ---
RUN pip install --upgrade pip setuptools wheel
RUN pip install -r requirements.txt

# --- Copy all app files ---
COPY . .

# --- Ensure the app is executable ---
RUN chmod +x main.py

# --- Default command to run your bot ---
CMD ["python", "main.py"]
