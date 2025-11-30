# ---------- Base Image ----------
FROM python:3.11-slim

# ---------- Set working directory ----------
WORKDIR /app

# ---------- Install dependencies ----------
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# ---------- Copy application ----------
COPY . .

# ---------- Expose port ----------
ENV PORT=8080
EXPOSE ${PORT}

# ---------- Start Gunicorn ----------
# Use shell form to expand $PORT at runtime
# Force Gunicorn to ignore gunicorn.conf.py by passing empty -c ''
CMD ["sh", "-c", "exec gunicorn wsgi:app \
  --bind 0.0.0.0:${PORT:-8080} \
  --workers 2 \
  --worker-class gthread \
  --threads 1 \
  --timeout 120 \
  --graceful-timeout 120 \
  --log-level debug \
  --capture-output \
  --enable-stdio-inheritance \
  -c ''"]
