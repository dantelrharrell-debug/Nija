FROM python:3.11-slim

WORKDIR /app

# Install git for pip git+https installs
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install --upgrade -r requirements.txt

COPY . .

RUN chmod +x ./start_all.sh

EXPOSE 5000
CMD ["./start_all.sh"]
