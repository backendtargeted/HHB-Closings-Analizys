FROM node:18-alpine as build

WORKDIR /app

# Same-origin `/api` via nginx, or full API URL for split Easypanel (browser → API directly).
# Runtime: BACKEND_UPSTREAM=host:port for nginx /api → Gunicorn.
#   docker compose: default backend:8000 matches service name "backend".
#   Easypanel Swarm: set in the UI service env to your API service DNS + 8000, e.g.
#     api:8000  or  crm-reports_api:8000  (see "docker service ls" / same-stack DNS).
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY . .

# Build the application
RUN npm run build

# Production stage
FROM nginx:alpine

# Compose: service name is "backend". Easypanel Swarm: set BACKEND_UPSTREAM=api:8000 (or crm-reports_api:8000).
ENV BACKEND_UPSTREAM=backend:8000

# Stock image ships *.template here; envsubst breaks real nginx $vars. Remove templates; use static conf + sed.
RUN rm -f /etc/nginx/templates/*.template

# Copy built files from build stage
COPY --from=build /app/dist /usr/share/nginx/html

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.d/05-replace-backend-upstream.sh /docker-entrypoint.d/05-replace-backend-upstream.sh
RUN sed -i 's/\r$//' /docker-entrypoint.d/05-replace-backend-upstream.sh \
    && chmod +x /docker-entrypoint.d/05-replace-backend-upstream.sh

# Copy logo
COPY public/HHB-Logo-600x143.webp /usr/share/nginx/html/HHB-Logo-600x143.webp

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
