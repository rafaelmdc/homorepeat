FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="homorepeat-web" \
      org.opencontainers.image.description="Django development runtime for the HomoRepeat web app" \
      org.opencontainers.image.source="https://github.com/rafaelmdc/homorepeat" \
      org.opencontainers.image.vendor="HomoRepeat" \
      org.opencontainers.image.licenses="MIT"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md manage.py /opt/homorepeat/
COPY apps /opt/homorepeat/apps
COPY config /opt/homorepeat/config
COPY static /opt/homorepeat/static
COPY templates /opt/homorepeat/templates
COPY web_tests /opt/homorepeat/web_tests

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install /opt/homorepeat

WORKDIR /app

ENV DJANGO_SETTINGS_MODULE=config.settings
