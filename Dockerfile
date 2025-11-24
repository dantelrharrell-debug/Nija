# --- Base image ---
FROM python:3.12-slim

# --- Set working directory ---
WORKDIR /app

# --- Copy only needed files ---
COPY web/ ./web/
COPY bot/ ./bot/
COPY vendor/coinbase_advanced_py/ ./vendor/coinbase_advanced_py/
COPY .env ./
COPY gunicorn.conf.py ./

# --- Install dependencies ---
RUN pip install --upgrade pip setuptools wheel \
    && pip install flask gunicorn requests

# --- Set environment variables ---
ENV PYTHONPATH=/app/web:/app/vendor/coinbase_advanced_py
ENV FLASK_ENV=production

# --- Expose web port ---
EXPOSE 5000

# --- Start Gunicorn ---
CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
