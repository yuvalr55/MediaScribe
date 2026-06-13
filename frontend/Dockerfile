# Build the static bundle, then serve it via nginx which also proxies /api.
# Vite embeds VITE_* vars at compile time, so they arrive as build args.
FROM node:20-alpine AS build

# Declare args first so they are in scope for the RUN step.
ARG VITE_API_BASE_URL=/api
ARG VITE_MAX_UPLOAD_MB=2048
ARG VITE_POLL_INTERVAL_MS=1500
ARG VITE_API_AUTH_TOKEN=
# Expose them as env vars so Vite picks them up during `npm run build`.
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_MAX_UPLOAD_MB=$VITE_MAX_UPLOAD_MB \
    VITE_POLL_INTERVAL_MS=$VITE_POLL_INTERVAL_MS \
    VITE_API_AUTH_TOKEN=$VITE_API_AUTH_TOKEN

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
