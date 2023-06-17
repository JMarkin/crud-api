# syntax=docker/dockerfile:1.2
FROM python:3.10

ENV POETRY_HOME=/poetry \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPYCACHEPREFIX=/tmp \
    PATH=/poetry/bin:$PATH

RUN pip install -U pip && \
    python3 -m venv $POETRY_HOME && \
    $POETRY_HOME/bin/pip install poetry

RUN python -m venv /root/venv

ENV VIRTUAL_ENV=/root/venv \
    PATH=/root/venv/bin:$PATH

RUN mkdir /app
WORKDIR /app

RUN --mount=type=bind,rw,source=.,target=/app poetry install --no-root

VOLUME /venv

