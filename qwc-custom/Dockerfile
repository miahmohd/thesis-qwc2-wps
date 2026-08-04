FROM node:24-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run prod

FROM sourcepole/qwc-map-viewer-base:latest-2026-lts

COPY --from=build /app/prod /qwc2
