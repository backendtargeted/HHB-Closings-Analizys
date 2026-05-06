FROM node:18-alpine as build

WORKDIR /app

# Browser must call same-origin `/api` so nginx (port 3300) can proxy to the backend.
# Override at image build time if needed: docker compose build --build-arg VITE_API_URL=https://example.com/api
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

# Copy built files from build stage
COPY --from=build /app/dist /usr/share/nginx/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy logo
COPY public/HHB-Logo-600x143.webp /usr/share/nginx/html/HHB-Logo-600x143.webp

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
