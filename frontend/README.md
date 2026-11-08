# Weather Station - Frontend

Public, no-login debug dashboard for the weather station. Built with [Vite](https://vitejs.dev/), React, TypeScript, [TanStack Query](https://tanstack.com/query) and [Router](https://tanstack.com/router), Tailwind CSS, [shadcn/ui](https://ui.shadcn.com/) and [Recharts](https://recharts.org/).

## Layout

- `src/routes/_layout/index.tsx` is the **Wind** page. It polls `/api/v1/readings/latest` every second and shows stat tiles, a collector Live/Stale badge and a wind speed + gust chart (5 m / 1 h / 24 h).
- `src/components/Wind/` holds the page's tiles, status badge and chart.
- `src/lib/api.ts` is the hand-written, typed fetch layer. Keep it in sync with `backend/app/models.py` and `backend/app/api/routes/readings.py`. URLs are relative (prefixed with `VITE_API_URL` if set), so the built app works wherever FastAPI serves it.
- `src/components/Sidebar/AppSidebar.tsx` lists one item per sensor page. Add a route under `src/routes/_layout/` and an item there for each new sensor.
- Chart colors are CSS tokens (`--series-*`, `--chart-*`, `--status-*`) in `src/index.css`, with separate light and dark values.

## Commands

Run from the repo root (bun is not required on the host; see below):

```bash
bun install
bun run dev                          # Vite on :5173, proxies /api to http://localhost:8000
bun run --filter frontend lint       # Biome
bun run --filter frontend build      # tsc + vite build into backend/app/frontend
bun run --filter frontend test       # Playwright smoke test (tests/wind.spec.ts)
```

Point the dev proxy elsewhere with `VITE_PROXY_TARGET=http://raspberrypi.local:8000 bun run dev`.

Without bun installed, run the same commands in Docker from the repo root:

```bash
docker run --rm -v "$PWD":/app -w /app oven/bun:1 bun run --filter frontend build
```

## Generated client (optional)

`openapi-ts.config.ts` and the `generate-client` script are kept for later, but nothing uses a generated client today. To try it, save `http://localhost:8000/api/v1/openapi.json` as `frontend/openapi.json` and run `bun run --filter frontend generate-client`.
