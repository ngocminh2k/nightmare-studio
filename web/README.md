# Nightmare Studio Web

Canonical Next.js operator UI for Nightmare Studio. It has no independent state or database: `/api/*` is a same-origin proxy to the FastAPI service at `NIGHTMARE_API_BASE_URL` (default `http://127.0.0.1:8000`).

```powershell
npm install
npm run dev
```

Open `http://127.0.0.1:3001` after starting FastAPI from the parent directory.

```powershell
npm run test:coverage
npm run test:e2e
npx tsc --noEmit
npm run lint
npm run build
```
