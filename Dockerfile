FROM python:3.12-slim

# Build-time args / environment
ENV POETRY_VERSION=1.7.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# Install system deps and Poetry
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl \
 && pip install --upgrade pip setuptools wheel \
 && pip install "poetry==${POETRY_VERSION}" \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

# Copy only pyproject and lock first to leverage Docker cache
COPY pyproject.toml poetry.lock* /app/

# Configure Poetry and install dependencies (system-wide because virtualenvs.create=false)
RUN poetry config virtualenvs.create false \
 && poetry install --no-root --no-dev

# Copy the rest of the project
COPY . /app

# Your runtime command (adjust as needed)
CMD ["gunicorn", "web.wsgi:app", "--bind", "0.0.0.0:5000"]
