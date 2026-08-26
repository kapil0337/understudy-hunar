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

# NEXT_PUBLIC_* vars are inlined into the client bundle at build time, not read at container
# start — so this must be an ARG available to `npm run build`, not just a runtime ENV.
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
RUN npm run build

ENV NODE_ENV=production
EXPOSE 3000

CMD ["npm", "run", "start"]
