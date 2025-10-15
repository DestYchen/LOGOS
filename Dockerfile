FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libreoffice \
        libreoffice-writer \
        libreoffice-core \
        ghostscript \
        fonts-dejavu \
        fonts-liberation \
        fonts-noto \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml SPEC.md ./
COPY docs ./docs
COPY app ./app

RUN pip install --no-cache-dir "pip<24.1" "setuptools>=67" wheel \
    && pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
