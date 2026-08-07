# Restaurant Agent MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a demonstrable MVP for a restaurant store analysis Agent with two business modules: pre-opening potential analysis and post-opening operating diagnosis.

**Architecture:** Use a TypeScript Next.js frontend for forms, uploads, dashboards, and report rendering. Use a Python FastAPI backend for CSV processing, pandas metric calculation, and a lightweight Plan-and-Execute Agent that routes requests, calls deterministic tools, verifies evidence, and returns structured reports.

**Tech Stack:** Next.js + React + TypeScript, FastAPI, Pydantic, SQLAlchemy, SQLite, pandas, pytest, OpenAPI-generated or manually mirrored TypeScript API types.

---

## Round Overview

The MVP should be implemented in 7 fixed rounds. Each round must end with a runnable state and a clear demo checkpoint.

| Round | Theme | Main Outcome |
| --- | --- | --- |
| 1 | Repository scaffold | Frontend and backend can both start |
| 2 | Backend domain model | SQLite schema, API skeleton, sample data |
| 3 | Metrics engine | Deterministic restaurant metrics work |
| 4 | Agent core | Plan-and-Execute returns structured reports |
| 5 | Frontend flows | User can submit pre-open form and upload CSV |
| 6 | Dashboard and report UI | Metrics, evidence, risks, and actions are visible |
| 7 | Demo hardening | Sample cases, tests, README, stable demo path |

## Round 1: Project Scaffold

**Goal:** Create a clean full-stack project skeleton with working dev commands.

**Files:**

- Create: `frontend/`
- Create: `backend/`
- Create: `backend/app/main.py`
- Create: `backend/requirements.txt`
- Create: `backend/pytest.ini`
- Create: `backend/tests/test_health.py`
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/app/page.tsx`
- Create: `README.md`

**Backend scope:**

- FastAPI app.
- `/health` endpoint.
- pytest setup.

**Frontend scope:**

- Next.js app.
- Home page with two cards:
  - 开店前潜力分析
  - 开店后经营诊断

**Commands:**

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\pytest
.\.venv\Scripts\uvicorn app.main:app --reload
```

```powershell
cd frontend
npm install
npm run dev
```

**Acceptance:**

- `GET /health` returns `{ "status": "ok" }`.
- Backend tests pass.
- Frontend loads a page with two business entry cards.

**Implementation checklist:**

- [ ] Create backend FastAPI scaffold.
- [ ] Add backend dependency file.
- [ ] Add `/health` endpoint.
- [ ] Add pytest health test.
- [ ] Create frontend Next.js TypeScript scaffold.
- [ ] Add home page with business entry cards.
- [ ] Document local run commands in `README.md`.
- [ ] Run backend tests.
- [ ] Start backend and frontend once.

## Round 2: Backend Domain Model and Sample Data

**Goal:** Define the minimum backend data model and seed enough sample data for later rounds.

**Files:**

- Create: `backend/app/db/session.py`
- Create: `backend/app/db/models.py`
- Create: `backend/app/schemas/common.py`
- Create: `backend/app/schemas/pre_open.py`
- Create: `backend/app/schemas/operating.py`
- Create: `backend/app/api/projects.py`
- Create: `backend/app/api/pre_open.py`
- Create: `backend/app/api/files.py`
- Modify: `backend/app/main.py`
- Create: `backend/sample_data/orders.csv`
- Create: `backend/sample_data/menu_items.csv`
- Create: `backend/sample_data/reviews.csv`
- Create: `backend/tests/test_models.py`
- Create: `backend/tests/test_pre_open_api.py`

**Minimum tables:**

- `projects`
- `pre_open_inputs`
- `uploaded_files`
- `orders`
- `menu_items`
- `reviews`
- `analysis_runs`
- `analysis_results`

**API scope:**

- `POST /projects`
- `POST /pre-open/analyze`
- `POST /files/upload`

At this round, `/pre-open/analyze` can return a basic placeholder structure computed by simple formulas, not the final Agent report.

**Acceptance:**

- Database initializes automatically in local dev.
- Project creation works.
- Pre-open input can be submitted and stored.
- Sample CSV files exist and match the planned schema.
- Tests pass.

**Implementation checklist:**

- [ ] Add SQLAlchemy session setup.
- [ ] Add minimal ORM models.
- [ ] Add Pydantic request/response schemas.
- [ ] Add project creation API.
- [ ] Add pre-open analyze API with simple stored result.
- [ ] Add upload API that stores files under `backend/storage/uploads`.
- [ ] Add sample order, menu, and review CSV files.
- [ ] Add tests for model creation.
- [ ] Add tests for pre-open API.
- [ ] Run pytest.

## Round 3: Deterministic Metrics Engine

**Goal:** Build the core pandas/SQL metric layer before adding LLM logic.

**Files:**

- Create: `backend/app/services/data_cleaning_service.py`
- Create: `backend/app/services/schema_mapping_service.py`
- Create: `backend/app/services/metric_service.py`
- Create: `backend/app/tools/break_even_tool.py`
- Create: `backend/app/tools/revenue_tool.py`
- Create: `backend/app/tools/menu_tool.py`
- Create: `backend/app/tools/review_tool.py`
- Create: `backend/tests/test_metric_service.py`
- Create: `backend/tests/test_tools.py`

**Metric scope:**

Pre-opening:

- Estimated daily fixed cost.
- Estimated break-even revenue.
- Estimated break-even orders.
- Investment pressure score.
- Franchise warning flags.

Post-opening:

- Total revenue.
- Daily revenue.
- Order count.
- Average order value.
- Gross profit estimate.
- Gross margin estimate.
- Menu item sales.
- Menu item profit contribution.
- Menu four-quadrant classification.
- Basic review topic counts.

**Review topic MVP keywords:**

- 味道
- 分量
- 价格
- 服务
- 环境
- 卫生
- 出餐慢
- 配送
- 漏送
- 包装

**Acceptance:**

- Metrics are calculated without LLM.
- Tests verify numeric calculations on sample data.
- Tool outputs are structured JSON-compatible dictionaries.

**Implementation checklist:**

- [ ] Implement CSV cleaning for time, numeric amount, quantity, and missing values.
- [ ] Implement schema mapping validation for required order/menu/review fields.
- [ ] Implement break-even formulas.
- [ ] Implement revenue metrics.
- [ ] Implement menu matrix metrics.
- [ ] Implement review keyword topic metrics.
- [ ] Add tests for break-even calculation.
- [ ] Add tests for revenue calculation.
- [ ] Add tests for menu matrix classification.
- [ ] Add tests for review topic extraction.
- [ ] Run pytest.

## Round 4: Plan-and-Execute Agent Core

**Goal:** Add the Agent layer that routes stage, plans tool calls, executes tools, synthesizes a report, and verifies evidence.

**Files:**

- Create: `backend/app/agents/state.py`
- Create: `backend/app/agents/router.py`
- Create: `backend/app/agents/planner.py`
- Create: `backend/app/agents/executor.py`
- Create: `backend/app/agents/synthesizer.py`
- Create: `backend/app/agents/verifier.py`
- Create: `backend/app/agents/prompts.py`
- Create: `backend/app/services/agent_service.py`
- Create: `backend/app/services/report_service.py`
- Create: `backend/app/api/operating.py`
- Create: `backend/app/api/analysis.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_agent_router.py`
- Create: `backend/tests/test_agent_service.py`

**Agent MVP behavior:**

- `StageRouter` chooses `pre_open` or `operating`.
- `Planner` returns a fixed structured plan based on stage and intent.
- `Executor` calls deterministic tools.
- `Synthesizer` can use an LLM if `OPENAI_API_KEY` exists, otherwise falls back to deterministic template text.
- `Verifier` checks every major conclusion has at least one metric or warning as evidence.

**API scope:**

- `POST /operating/analyze`
- `GET /analysis/{analysis_id}`

**Acceptance:**

- Pre-open analysis returns:
  - summary
  - scores
  - risks
  - evidence
  - actions
- Operating analysis returns:
  - summary
  - metrics
  - menu matrix
  - review topics
  - risks
  - evidence
  - actions
- Tests pass without requiring an LLM API key.

**Implementation checklist:**

- [ ] Define Agent state schema.
- [ ] Implement stage router.
- [ ] Implement fixed planner templates for both stages.
- [ ] Implement executor tool dispatch.
- [ ] Implement synthesizer with template fallback.
- [ ] Implement evidence verifier.
- [ ] Implement report service.
- [ ] Add operating analysis API.
- [ ] Add analysis result retrieval API.
- [ ] Add tests for routing.
- [ ] Add tests for agent service with sample data.
- [ ] Run pytest.

## Round 5: Frontend Input Flows

**Goal:** Build the user-facing input flows for both business modules.

**Files:**

- Create: `frontend/lib/api.ts`
- Create: `frontend/lib/types.ts`
- Create: `frontend/components/StageSelector.tsx`
- Create: `frontend/components/PreOpenForm.tsx`
- Create: `frontend/components/CsvUploader.tsx`
- Create: `frontend/components/ColumnMapper.tsx`
- Create: `frontend/app/pre-open/page.tsx`
- Create: `frontend/app/operating/page.tsx`
- Modify: `frontend/app/page.tsx`

**Frontend scope:**

- Home page routes to two modules.
- Pre-open form submits to backend.
- Operating page uploads three CSV files:
  - orders
  - menu_items
  - reviews
- Minimal client-side validation.
- Show loading and error states.

**Acceptance:**

- User can complete pre-open form and receive an analysis ID.
- User can upload sample CSV files and trigger operating analysis.
- Failed API calls show readable errors.
- TypeScript build passes.

**Implementation checklist:**

- [ ] Define shared frontend types for reports, metrics, risks, evidence, actions.
- [ ] Implement API client wrapper.
- [ ] Implement stage selector.
- [ ] Implement pre-open form.
- [ ] Implement CSV uploader.
- [ ] Implement operating analysis page.
- [ ] Connect frontend pages to backend APIs.
- [ ] Add loading states.
- [ ] Add error states.
- [ ] Run `npm run build`.

## Round 6: Dashboard and Report UI

**Goal:** Make the MVP visually demonstrable with metrics, charts, risks, evidence, and actions.

**Files:**

- Create: `frontend/components/MetricCards.tsx`
- Create: `frontend/components/RevenueChart.tsx`
- Create: `frontend/components/MenuMatrix.tsx`
- Create: `frontend/components/ReviewTopics.tsx`
- Create: `frontend/components/RiskPanel.tsx`
- Create: `frontend/components/EvidencePanel.tsx`
- Create: `frontend/components/AgentReport.tsx`
- Create: `frontend/components/ActionList.tsx`
- Create: `frontend/app/analysis/[id]/page.tsx`
- Modify: `frontend/package.json`

**UI scope:**

- Report page shows:
  - summary
  - core metrics
  - risk list
  - evidence list
  - action list
- Operating report additionally shows:
  - revenue chart
  - menu matrix
  - review topics
- Pre-open report additionally shows:
  - break-even summary
  - investment/franchise/location risk blocks

**Chart library:**

- Use Recharts for MVP.

**Acceptance:**

- Analysis report page renders both pre-open and operating reports.
- Sample operating case shows at least one chart.
- Sample report clearly separates conclusion, evidence, and actions.
- TypeScript build passes.

**Implementation checklist:**

- [ ] Install chart dependency.
- [ ] Implement metric cards.
- [ ] Implement revenue chart.
- [ ] Implement menu matrix visual.
- [ ] Implement review topics panel.
- [ ] Implement risk panel.
- [ ] Implement evidence panel.
- [ ] Implement action list.
- [ ] Implement analysis detail page.
- [ ] Verify pre-open report rendering.
- [ ] Verify operating report rendering.
- [ ] Run `npm run build`.

## Round 7: Demo Hardening and Documentation

**Goal:** Make the project stable enough for interview demo and repository review.

**Files:**

- Modify: `README.md`
- Create: `docs/demo-script.md`
- Create: `docs/api-contract.md`
- Create: `backend/sample_data/pre_open_case.json`
- Create: `backend/sample_data/demo_notes.md`
- Create: `frontend/app/demo/page.tsx`
- Create: `backend/tests/test_end_to_end_analysis.py`

**Demo cases:**

- Case A: 准备加盟奶茶店，投资偏高，加盟风险明显。
- Case B: 已开面馆，营业额下滑，菜品结构和差评暴露问题。

**README must include:**

- Project positioning.
- Architecture summary.
- Tech stack.
- Local setup.
- Demo flow.
- Sample data explanation.
- What is Agentic in this project.
- What is intentionally not implemented in MVP.

**Acceptance:**

- One command sequence can start backend and frontend.
- Demo script can be followed in under 5 minutes.
- Backend tests pass.
- Frontend build passes.
- User can run both demo cases.

**Implementation checklist:**

- [ ] Add sample pre-open case JSON.
- [ ] Add backend end-to-end analysis test.
- [ ] Add demo page with links to both flows.
- [ ] Document API contract.
- [ ] Write demo script.
- [ ] Update README.
- [ ] Run backend tests.
- [ ] Run frontend build.
- [ ] Manually walk through demo cases.

## Fixed Round Rules

Use these rules to keep the project from expanding:

1. Do not add authentication in MVP.
2. Do not add payment or user roles in MVP.
3. Do not add external map, Meituan, Dianping, or delivery platform APIs in MVP.
4. Do not add PDF export in MVP.
5. Do not add vector database unless the deterministic and Agent flows are already complete.
6. Do not let LLM compute numeric metrics.
7. Do not proceed to frontend polish until backend analysis APIs are stable.
8. Every round must end with tests or a manual demo checkpoint.

## Recommended Commit Sequence

```text
feat: scaffold full stack restaurant agent
feat: add backend domain model and sample data
feat: implement restaurant metrics engine
feat: add plan execute agent workflow
feat: build mvp input flows
feat: render diagnosis dashboard and reports
docs: add demo script and harden mvp docs
```

## Success Criteria

The MVP is complete when:

- A user can run the backend and frontend locally.
- A user can submit a pre-opening case and get a risk report.
- A user can upload operating CSV files and get a diagnosis report.
- Reports include metrics, evidence, risks, and actions.
- Numeric metrics come from deterministic backend tools.
- Agent behavior is visible through stage routing, planning, tool execution, synthesis, and verification.
- The README explains the project clearly enough for an interviewer to understand it in two minutes.

