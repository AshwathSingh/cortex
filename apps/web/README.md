# Cortex web

The single Cortex frontend, built with Next.js, React, TypeScript, and Tailwind.

## Getting Started

From the repository root:

```bash
npm install --prefix apps/web
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

Requests to `/api/*` are proxied to FastAPI at `http://localhost:8000`. Copy
`.env.example` to `.env.local` only when FastAPI runs at a different origin.

Run `npm test`, `npm run lint`, and `npm run build` from the repository root
before submitting frontend changes.
