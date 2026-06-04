# Full-stack image for single-service deploy (e.g. Easypanel build path "/"):
# Gunicorn serves the Flask API at /api/* and the built SPA on /.
# Set container port / health check to 8000 in the panel.

FROM node:18-alpine AS frontend-build

WORKDIR /fe
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY backend/app/ ./app/
COPY --from=frontend-build /fe/dist ./static

ENV FRONTEND_DIST=/app/static

# Mount a persistent volume at /app/reports in production (Easypanel); otherwise reports are lost on rebuild.
RUN mkdir -p uploads exports reports

# Easypanel and similar hosts often set PORT; default keeps local/docker-compose expectations.
EXPOSE 8000

CMD ["sh", "-c", "gunicorn -b 0.0.0.0:${PORT:-8000} -w 1 --timeout 600 --graceful-timeout 120 app.main:app"]
