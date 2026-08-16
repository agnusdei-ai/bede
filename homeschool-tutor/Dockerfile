# Node 24 (active LTS, security support through 2028-04-30), not 20.
#
# Node 20 reached end-of-life on 2026-04-30 and had been unsupported for
# three months before this was noticed. That matters more than it looks:
# `npm audit` and Dependabot both audit PACKAGES, not the runtime under
# them, so a repo can sit at zero advisories — as this one did — while
# building on a Node that will never receive another security patch, for
# OpenSSL, HTTP parsing, or anything else. Nothing in the toolchain
# reports it, which is why it needs a comment rather than just a bump.
#
# This is a build stage only (the runtime image below is nginx, serving
# static assets), so the blast radius is the build, not the served app.
# It is still the supply chain that produces what families run.
FROM node:24-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# Vite reads import.meta.env.VITE_* at build time and inlines the value into
# the bundle, so the deployment's language has to be known here rather than
# passed to the running container. docker-compose.yml feeds this from the
# same LOCALE the api service uses, so the login screen opens in the language
# the deployment actually chose. Both bundles ship either way and the login
# toggle switches between them live (see docs/LOCALIZATION.md) — this only
# decides which one paints first.
ARG VITE_LOCALE=en
ENV VITE_LOCALE=$VITE_LOCALE
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
