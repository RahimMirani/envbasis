FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system envbasis \
    && adduser --system --ingroup envbasis --home /nonexistent envbasis

COPY pyproject.toml README.md ./
COPY --chown=envbasis:envbasis src ./src

RUN pip install --no-cache-dir .

USER envbasis

EXPOSE 8080

CMD ["uvicorn", "envbasis_proxy.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
