# Dockerfile - canonical for NIJA repo
FROM python:3.12-slim

LABEL maintainer="Dante Harrell <your-email@example.com>"

# set working dir
WORKDIR /app

# system deps (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# copy constraints (if present) and requirements
COPY constraints.txt requirements.txt ./

# install python deps (use constraints if present)
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    if [ -f constraints.txt ]; then pip install --no-cache-dir -r requirements.txt -c constraints.txt; \
    else pip install --no-cache-dir -r requirements.txt; fi

# copy the whole repo into the image
COPY . .

# ensure src is on the python path so imports like `from src.xxx` work
ENV PYTHONPATH=/app/src

# expose port (gunicorn will bind to this)
EXPOSE 5000

# recommend running under non-root, but keep simple for now
# create app user (optional)
RUN useradd -m -d /home/nija nija || true
USER nija

# entrypoint: run gunicorn pointing to the canonical entry: src.wsgi:app
# ensure gunicorn.conf.py is present at repo root
CMD ["gunicorn", "-c", "gunicorn.conf.py", "src.wsgi:app"]
