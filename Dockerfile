FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
RUN useradd --uid 10001 --create-home shabsanj && mkdir /app/data && chown shabsanj:shabsanj /app/data
COPY backend/*.py backend/
COPY data/catalog.json data/tours.json data/tickets.json seed-data/
COPY --from=frontend /app/frontend/dist frontend/dist
RUN chmod -R a+rX /app/seed-data /app/frontend/dist /app/backend
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER shabsanj
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8765/api/health',timeout=3)); assert d['status']=='ok' and d['ticket_catalog_ready']"
CMD ["python", "-m", "backend.container_start"]
