FROM python:3.12-slim
WORKDIR /app/backend
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY templates/pptx/catalog.json /app/templates/pptx/catalog.json
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
RUN pip install --no-cache-dir .
WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
