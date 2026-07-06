FROM node:22-alpine AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci
COPY web/ .
RUN npm run build

FROM python:3.13-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Reranker disabled in deploy: sentence-transformers/torch is excluded from
# requirements-deploy.txt to fit the free-tier 512MB RAM ceiling.
ENV FINSIGHT_USE_RERANKER=0

COPY requirements-deploy.txt .
RUN pip install --no-cache-dir -r requirements-deploy.txt

COPY app/ app/
COPY ingest/ ingest/
COPY static/ static/
COPY data/manifest.json data/chunks.json data/facts.json data/
COPY data/chroma/ data/chroma/
COPY --from=web-build /static/dist/ static/dist/

EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
