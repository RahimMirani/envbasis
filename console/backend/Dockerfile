FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system envbasis \
    && adduser --system --ingroup envbasis --home /nonexistent envbasis

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=envbasis:envbasis alembic.ini ./
COPY --chown=envbasis:envbasis alembic ./alembic
COPY --chown=envbasis:envbasis app ./app

USER envbasis

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
