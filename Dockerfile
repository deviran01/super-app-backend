# Anar API: FastAPI on uvicorn, on the same base image as the host's other Python services.
# Content (data/, public/) is mounted at run time, so publishing a change needs no rebuild.
FROM python:3.11.17-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY scenarios ./scenarios

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin api
USER api

EXPOSE 8000
# Behind the host's nginx (and ArvanCloud): trust its X-Forwarded-* headers. The port is
# published on the host's loopback only, so only nginx (or another process on the host) can
# send them. A short graceful shutdown lets the statistics writer flush before Docker's kill.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header", \
     "--timeout-graceful-shutdown", "5"]
