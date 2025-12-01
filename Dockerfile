FROM python:3.11-slim

WORKDIR /usr/src/app

RUN apt-get update && apt-get install -y git build-essential && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH="/usr/src/app/cd/vendor:$PYTHONPATH"

EXPOSE 5000

CMD ["gunicorn", "-c", "gunicorn.conf.py", "web.wsgi:app"]
