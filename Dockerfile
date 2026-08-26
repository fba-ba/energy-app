FROM python:3.12-slim

WORKDIR /app

# Dépendances d'abord (couche de cache Docker).
COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY docker-entrypoint.sh ./

RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1
ENV ENERGY_DB_URL=sqlite:////data/app.db
ENV ENERGY_CACHE_DIR=/data/cache

RUN mkdir -p /data/cache && chmod +x /app/docker-entrypoint.sh

EXPOSE 8000 8501

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
