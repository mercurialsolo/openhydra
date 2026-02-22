FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OPENHYDRA_HOST=0.0.0.0 \
    OPENHYDRA_WEB_PORT=7070

WORKDIR /app

RUN useradd --create-home --shell /bin/bash hydra

COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src
COPY config /app/config
COPY skills /app/skills
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN python -m pip install --upgrade pip \
    && python -m pip install ".[web,embeddings]" \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

USER hydra

EXPOSE 7070

ENTRYPOINT ["docker-entrypoint.sh"]
