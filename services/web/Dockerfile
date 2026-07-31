FROM node:22-alpine AS build

WORKDIR /app

ARG VITE_APP_VERSION=1.0.0
ENV VITE_APP_VERSION=$VITE_APP_VERSION

COPY package.json package-lock.json* ./
# npm ci when a lockfile is committed, npm install on a fresh checkout.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . .
RUN npm run build

# ── serve ────────────────────────────────────────────────────────────────────
FROM caddy:2.8-alpine

COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile

EXPOSE 8080
