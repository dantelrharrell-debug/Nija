FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip
RUN pip install -r requirements.txt

CMD ["python", "-u", "main.py"]
