# Cortex frontend

Vite + React + TypeScript. Currently one screen: a form that submits a GitHub repo URL
to the backend ingest endpoint (T-7.6).

Requires Node `^20.19.0 || >=22.12.0`.

```
cd frontend
npm install
npm run dev        # http://localhost:5173
```

The dev server proxies `/api` to `http://localhost:8000`, so start the backend first
(see [../backend/README.md](../backend/README.md), then `uvicorn app.main:app --port 8000`
from `backend/`).

| Command | Purpose |
|---|---|
| `npm test` | Component tests (Vitest + Testing Library); no backend needed |
| `npm run build` | Type-check and production build |
| `npm run lint` | oxlint |

Layout: `src/api/ingest.ts` (API call and error mapping),
`src/components/RepoIngestForm.tsx` (the form). App-wide routing and layout are owned
by US-42; `src/App.tsx` is a placeholder shell.
