# Release Baseline

## Baseline

- Recorded at: 2026-08-14 +08:00
- Branch: `codex/agent-evals`
- Consolidation base: `8a0fbd1` plus the Phase 7 interview-release candidate
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

Result: `396 passed, 2 skipped`.

The skipped cases are the opt-in real Baidu smoke test and the opt-in live
Agent evaluation. They require explicit run flags and provider credentials;
both are intentionally excluded from the default regression suite to avoid
external instability and accidental model cost.

### Offline Agent evaluation

```powershell
cd backend
python -m scripts.run_agent_evals
```

Result: the safety gate passed all 30 cases. Current planning precision,
recall, exact-set accuracy, evidence validity, and safety pass rate are all
`1.0000`; unsupported numeric and normative claims are zero.

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

### Browser smoke

Result: a fresh SQLite database completed the demo-to-operating-report flow on
isolated ports. The report rendered revenue, break-even, channel, menu, review,
risk, evidence, and action sections; the browser console reported zero errors
and zero warnings.

## Release Gate

Before merging a release candidate, rerun all three checks above and verify:

- `git diff --check` returns no errors.
- No API key, local database, upload, provider payload, or generated build
  directory is tracked.
- The release branch worktree is clean.
