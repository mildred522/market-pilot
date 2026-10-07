# Source-based development

Run `powershell -ExecutionPolicy Bypass -File .\start.ps1` from the main checkout.
This builds the launcher first, stops on build failure, and binds its project root
to this checkout. A launcher found inside a Git worktree resolves the main checkout
by default; set `MARKET_PILOT_ROOT` explicitly to develop another checkout.

The launcher verifies `/dev-runtime` and `/api/dev-runtime` before reusing services.
A response from another directory or an older service is not considered ready.
If port 3000 or 8000 belongs to a recognizable older Market Pilot service, the
launcher stops its Node/Python process tree and starts the current checkout.
This also recovers a hung Next/Uvicorn process by checking the listener's command
line for the main checkout or its `.worktrees` siblings.
It never stops an unrecognized program using either port. The desktop shortcut passes
`--start`, so opening it starts or reuses the current workspace automatically. Only one
launcher window can run at a time; a repeated click keeps the existing window and service
ownership instead of creating another startup chain.

Backend development uses `backend/dev.py`: Uvicorn watches only `backend/app`,
including added Python modules. Generated files, uploads and database writes do
not trigger reloads. Frontend development uses Next HMR and `.next-dev`; production
builds use `.next` so a build cannot overwrite the development runtime cache.

If port `8000` is already occupied by another checkout, start this backend on an explicit alternate port and point the frontend at it:

```bash
MARKET_PILOT_API_PORT=8001 backend/.venv/bin/python backend/dev.py
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8001 npm --prefix frontend run dev
```

The default remains `127.0.0.1:8000`; changing the port does not change authentication or data-scope behavior.

Python/TypeScript source and route changes update automatically. Restart after
changing dependencies, environment variables or startup configuration. Database
schema changes still require an explicit compatible migration. Vercel requires
a separate deployment; local source updates do not publish themselves.
