# Release Baseline

## Baseline

- Recorded at: 2026-08-13 20:28 +08:00
- Branch: `feature/location-analysis`
- Consolidation base: `2e9f0b4`
- Platform: Windows x64

## Toolchain

| Component | Version |
| --- | --- |
| Python | 3.13.0 |
| Node.js | 22.14.0 |
| npm | 10.9.2 |
| .NET SDK | 8.0.400 |

## Verification

### Backend

```powershell
cd backend
python -m pytest -q
```

Result: `310 passed, 1 skipped`.

The skipped case is the opt-in real Baidu smoke test. It requires
`RUN_BAIDU_SMOKE=1`, a valid `BAIDU_MAP_AK`, and a matching provider IP
allowlist. It is intentionally excluded from the default regression suite.

### Frontend

```powershell
cd frontend
npm run build
```

Result: Next.js production compilation and TypeScript validation succeeded.
The build produced the dashboard, analysis report, demo, operating, and
pre-open routes.

### Windows launcher

```powershell
dotnet build launcher/MarketPilot.Launcher/MarketPilot.Launcher.csproj `
  --configuration Release
```

Result: build succeeded with zero warnings and zero errors.

## Release Gate

Before merging a release candidate, rerun all three checks above and verify:

- `git diff --check` returns no errors.
- No API key, local database, upload, provider payload, or generated build
  directory is tracked.
- The feature worktree is clean.
