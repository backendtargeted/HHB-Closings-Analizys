FROM node:18-alpine as build

WORKDIR /app

# Same-origin `/api` via nginx, or full API URL for split Easypanel (browser → API directly).
# Runtime: BACKEND_UPSTREAM=host:port for nginx proxy (default backend:8000 for compose).
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

ENV BACKEND_UPSTREAM=backend:8000

# Copy built files from build stage
COPY --from=build /app/dist /usr/share/nginx/html

# Templated config: envsubst writes /etc/nginx/conf.d/default.conf on container start
COPY default.conf.template /etc/nginx/templates/default.conf.template

# Copy logo
COPY public/HHB-Logo-600x143.webp /usr/share/nginx/html/HHB-Logo-600x143.webp

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
