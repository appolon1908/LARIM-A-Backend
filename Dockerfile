FROM python:3.13-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.13
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN groupadd --gid 10001 larimia && useradd --uid 10001 --gid larimia --no-create-home larimia \
    && mkdir -p /var/lib/larimia/storage && chown -R larimia:larimia /var/lib/larimia
COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "larimia.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
