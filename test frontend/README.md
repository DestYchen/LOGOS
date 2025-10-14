# SupplyHub Test Frontend

This is a fresh shadcn/ui + Vite React rewrite of the web console. It talks to the FastAPI backend via the new JSON endpoints exposed under `/web/api`.

## Prerequisites

- Node.js 18+
- pnpm / npm / yarn (examples below use npm)

## Getting started

```bash
cd "test frontend"
npm install
```

### Development server

```bash
# By default the app assumes the backend is served from http://localhost:8000/web
npm run dev

# If the backend runs on a different host/port:
VITE_API_BASE=http://localhost:9000/web npm run dev
```

The dev server runs on http://localhost:5173 and proxies API requests to the backend using the `VITE_API_BASE` origin you provide.

### Production build

```bash
npm run build
```

The build artefacts are emitted into `dist/`. The FastAPI router (`app/api/routes/web.py`) is already configured to serve static files from `test frontend/dist`, so after building, `/web/app` and `/web/app/*` will serve the compiled SPA.

Use `npm run preview` to run Vite’s static preview locally.

## Project structure

- `src/pages` – Upload, batch list, and batch detail screens.
- `src/lib/api.ts` – Fetch helpers that call the FastAPI endpoints.
- `src/components` – Reusable shadcn/ui-based components and the layout shell.

The UI mirrors the previous HTML flow: upload documents, monitor batch progress, review fields, and trigger validation/report downloads.
