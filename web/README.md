# web

Next.js 15 (App Router) + TypeScript strict + Tailwind + shadcn/ui frontend for Understudy.

## Local development

```bash
npm install
npm run dev
```

Or via the monorepo's `docker compose` setup — see the [root README](../README.md).

## Scripts

- `npm run dev` — dev server
- `npm run build` / `npm run start` — production build and serve
- `npm run lint` — eslint
- `npm run format` — prettier --write
- `npm run gen-api` (alias: `npm run gen:api`) — regenerate `src/lib/api/types.ts` from the
  backend's OpenAPI schema (`make gen-api` from the repo root does both steps: writes
  `src/lib/api/openapi.json`, then runs this)
- `npm run test` — vitest (component/logic unit tests, no browser)
- `npm run test:e2e` — Playwright, against seeded data (`make seed` from the repo root first) —
  see `playwright.config.ts` for what it expects already running

## Deployment

`Dockerfile` here is for local `docker compose` and self-hosting only. The production frontend
deploys to Vercel, which builds straight from git and does not run this Dockerfile.
