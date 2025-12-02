# ---------- Base image ----------
FROM python:3.11-slim

# ---------- Metadata ----------
LABEL maintainer="Dante Harrell <you@example.com>"

# ---------- Working dir ----------
WORKDIR /usr/src/app

# ---------- System deps ----------
RUN apt-get update && apt-get install -y --no-install-recommends \
        git build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---------- Upgrade pip/setuptools ----------
RUN python3 -m pip install --upgrade pip setuptools wheel

# ---------- Copy requirements and app ----------
COPY requirements.txt .
# Remove leftover merge markers if any
RUN sed -i '/^<<<<<<< HEAD$/,/^>>>>>>>/d' requirements.txt || true

# Install python deps (including from git if present)
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# Ensure common extras are present
RUN pip install --no-cache-dir python-dotenv gunicorn

# Copy app code
COPY . .

# Make entrypoint executable
RUN chmod +x ./entrypoint.sh

# Expose port
EXPOSE 5000

# Entrypoint
ENTRYPOINT ["/usr/src/app/entrypoint.sh"]

# Command (entrypoint will launch gunicorn)
CMD ["gunicorn", "web.wsgi:app", "-c", "gunicorn.conf.py"]
