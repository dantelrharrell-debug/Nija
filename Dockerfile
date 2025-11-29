FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        git \
        ca-certificates \
        dos2unix && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/app/
COPY web/ /app/web/
COPY bot/ /app/bot/

# Ensure folder exists
RUN mkdir -p /app/cd
COPY cd/ /app/cd/

EXPOSE 8080
CMD ["python", "-m", "app.main"]
