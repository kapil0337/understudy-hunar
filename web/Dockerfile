# syntax=docker/dockerfile:1
#
# For local docker compose and self-hosting only. Production deploys go to
# Vercel, which builds from git directly and does not run this file — see
# ../README.md.

FROM node:22-bookworm-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

ENV NODE_ENV=production
EXPOSE 3000

CMD ["npm", "run", "start"]
