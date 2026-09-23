# Knowhow UI

Vite + React + TypeScript SPA. Consumes the FastAPI `/api/*` surface.

## Dev

Start the API in one terminal:

```bash
uv run knowhow serve --host 127.0.0.1 --port 8765
```

Then:

```bash
pnpm install
pnpm dev
```

Vite proxies `/api` → `http://127.0.0.1:8765`. Open the printed local URL (default `http://127.0.0.1:5173`).

## Production build

```bash
pnpm build
```

Writes to `src/knowhow/web/static/`. `knowhow serve` serves that SPA at `/`. If `static/index.html` is missing, `/` returns a plain message to run `pnpm --dir frontend build`.
