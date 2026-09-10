FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system --no-cache .


FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH=/home/larimia/.local/bin:$PATH

RUN groupadd --system --gid 10001 larimia \
    && useradd --system --uid 10001 --gid 10001 \
       --home-dir /home/larimia --create-home larimia

WORKDIR /app
COPY --from=builder /usr/local /usr/local
COPY --chown=larimia:larimia src ./src
COPY --chown=larimia:larimia migrations ./migrations
COPY --chown=larimia:larimia scripts ./scripts
COPY --chown=larimia:larimia alembic.ini pyproject.toml README.md ./

USER 10001:10001
EXPOSE 8000

CMD ["uvicorn", "larimia.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
