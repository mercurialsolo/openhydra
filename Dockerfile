FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --shell /bin/bash hydra

COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src
COPY config /app/config
COPY skills /app/skills

RUN python -m pip install --upgrade pip \
    && python -m pip install .

USER hydra

ENTRYPOINT ["openhydra"]
CMD ["--help"]
