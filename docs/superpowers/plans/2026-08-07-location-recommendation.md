# 双模式选址与商圈推荐 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有开店前分析中加入可复用的手动点位分析与行政区商圈自动推荐，并把机会评分、数据可信度和财务结论分开呈现。

**Architecture:** 保留现有 `BaiduMapClient` 和快照仓库作为供应商边界，在其上增加分页多关键词采集、候选锚点生成、特征构建、评分和分析服务。FastAPI 负责请求校验与项目关联，Next.js 通过手动/自动分段入口调用两个分析接口；自动推荐只返回商圈中心，选择后把中心坐标带入手动分析。

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLAlchemy, httpx.MockTransport, pytest, Next.js 16, React 19, TypeScript.

---

### Task 1: 建立选址领域契约与计算模型

**Files:**
- Create: `backend/app/location/contracts.py`
- Create: `backend/app/location/feature_builder.py`
- Create: `backend/app/location/scorer.py`
- Create: `backend/app/location/__init__.py`
- Test: `backend/tests/test_location_scoring.py`

- [ ] **Step 1: Write failing tests** for multi-ring competitor counts, demand-proxy counts, confidence below 60, score boundaries, and the four conclusion labels.
- [ ] **Step 2: Run `pytest backend/tests/test_location_scoring.py -q`** and verify the new module is missing or assertions fail.
- [ ] **Step 3: Define typed dataclasses/Pydantic models** for normalized POI features, ring metrics, dimension scores, evidence, and analysis result. Use explicit fields for direct competitors, substitutes, transit, amenities, price coverage, opportunity score, confidence score, and conclusion.
- [ ] **Step 4: Implement `LocationFeatureBuilder`** to classify POIs by keyword/category, deduplicate by `uid`, calculate 300/500/800/1500m ring counts, price median/range, transit and amenity counts, and leave missing fields as missing.
- [ ] **Step 5: Implement `LocationScorer`** with configurable 25/25/20/15/15 weights, independent confidence components, and the approved conclusion rules. Low confidence must return `继续调研`.
- [ ] **Step 6: Run the focused tests and then `pytest backend -q`**; expected focused and existing suites pass.
- [ ] **Step 7: Commit** with `feat: add location analysis scoring contracts`.

### Task 2: Upgrade Baidu collection and cache reuse

**Files:**
- Modify: `backend/app/external_context/baidu_client.py`
- Modify: `backend/app/external_context/contracts.py`
- Modify: `backend/app/external_context/snapshot_service.py`
- Create: `backend/app/location/collector.py`
- Test: `backend/tests/test_baidu_map_client.py`
- Test: `backend/tests/test_location_collector.py`

- [ ] **Step 1: Add failing tests** for page 0/page 1 requests, `page_size <= 20`, repeated `uid` removal across keywords, and provider error classification.
- [ ] **Step 2: Run the focused tests** and confirm pagination/collector behavior is absent.
- [ ] **Step 3: Extend `BaiduMapClient`** with `search_nearby_page` and `search_region_page`, retaining `search_nearby` compatibility. Do not expose the AK in returned models or logs.
- [ ] **Step 4: Implement `PoiCollector.collect_competitors`** using category keyword groups, all four rings, bounded pagination, and `uid` deduplication while retaining matched keywords.
- [ ] **Step 5: Add reusable snapshot lookup for exact query scope and seven-day expiry**; only standard metrics/evidence are persisted, never raw provider payloads.
- [ ] **Step 6: Run collector, client, snapshot, and full backend tests**; expected all pass.
- [ ] **Step 7: Commit** with `feat: add paginated baidu poi collection`.

### Task 3: Add candidate generation and location analysis service

**Files:**
- Create: `backend/app/location/candidates.py`
- Create: `backend/app/location/service.py`
- Create: `backend/app/location/evidence.py`
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/db/session.py`
- Test: `backend/tests/test_location_candidates.py`
- Test: `backend/tests/test_location_service.py`

- [ ] **Step 1: Write failing tests** for 400m anchor clustering, maximum 30 raw anchors, maximum 10 deep analyses, 3-5 recommendation output, insufficient candidates, and manual snapshot reuse.
- [ ] **Step 2: Run the focused tests** and verify the new service does not exist.
- [ ] **Step 3: Add `LocationAnalysis` persistence** containing mode, input scope, center, status, normalized result JSON, evidence JSON, warnings, and timestamps; initialize it through existing SQLAlchemy metadata creation.
- [ ] **Step 4: Implement `CandidateGenerator`** for region-search anchor types, deterministic 400m clustering, explainable representative centers, and bounded candidate counts.
- [ ] **Step 5: Implement `LocationAnalysisService.analyze_manual`** to collect POIs, build features, score the point, attach source/range/observation evidence, and persist the result.
- [ ] **Step 6: Implement `analyze_recommendations`** to region-search anchors, cluster, run low-cost screening, deep-analyze top 10, sort by opportunity then confidence, and return up to 5 candidates without inventing missing candidates.
- [ ] **Step 7: Add `GET` retrieval by analysis ID** and ensure supplier failures produce classified warnings plus stale-cache or low-confidence fallback.
- [ ] **Step 8: Run all backend tests** and commit `feat: add manual and regional location analysis service`.

### Task 4: Expose FastAPI contracts and endpoints

**Files:**
- Create: `backend/app/schemas/location.py`
- Create: `backend/app/api/location.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_location_api.py`

- [ ] **Step 1: Write failing API tests** for valid manual coordinate input, address-or-coordinate validation, recommendations with default/max candidate limits, missing AK configuration, provider errors, and analysis retrieval.
- [ ] **Step 2: Run `pytest backend/tests/test_location_api.py -q`** and verify routes return 404.
- [ ] **Step 3: Define request/response schemas** including city, district, category, coordinate system, optional finance assumptions, mode, candidate list, score breakdown, evidence, risks, and transition center coordinates.
- [ ] **Step 4: Register `POST /pre-open/location/manual-analysis`, `POST /pre-open/location/recommendations`, and `GET /pre-open/location/analyses/{analysis_id}`** with dependency-injected database and service objects.
- [ ] **Step 5: Validate candidate count 1-10, radius bounds, coordinates, and reject an analysis conclusion that lacks required evidence.
- [ ] **Step 6: Run the API tests and full backend suite**; commit `feat: expose location analysis api`.

### Task 5: Build the frontend dual-mode workflow

**Files:**
- Create: `frontend/components/LocationAnalysis.tsx`
- Modify: `frontend/app/pre-open/page.tsx`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/app/globals.css`

- [ ] **Step 1: Add typed client tests or compile-time fixtures** for both request payloads and response rendering fields.
- [ ] **Step 2: Add API client functions** for manual analysis, recommendations, and analysis retrieval using the existing `request` helper.
- [ ] **Step 3: Add a segmented manual/automatic control** to the pre-open page. Manual mode accepts address or BD-09 latitude/longitude and optional finance inputs; automatic mode accepts city, district, category, radius, and candidate count.
- [ ] **Step 4: Render recommendation results** as a ranked structured list showing center, opportunity score, confidence, reasons, risks, evidence age, and an `评估具体铺位` action that switches to manual mode and carries coordinates.
- [ ] **Step 5: Render manual results** with separate opportunity, confidence, and financial sections; show only `继续调研` when required inputs or confidence are insufficient.
- [ ] **Step 6: Add loading, empty, provider-error, and retry states without exposing the AK**; keep layout usable on mobile and desktop.
- [ ] **Step 7: Run `npm run build` and existing frontend checks**; commit `feat: add dual-mode location workflow`.

### Task 6: Controlled real-data smoke test and documentation

**Files:**
- Create: `backend/tests/test_location_real_smoke.py`
- Modify: `README.md`
- Modify: `docs/api-contract.md`
- Create: `docs/location-analysis-operations.md`

- [ ] **Step 1: Add an opt-in smoke test** guarded by `RUN_BAIDU_SMOKE=1` and `BAIDU_MAP_AK`; use a fixed Chengdu coordinate and assert only response shape, bounded count, and no secret output.
- [ ] **Step 2: Run default tests** and verify the real smoke test is skipped unless explicitly enabled.
- [ ] **Step 3: Document environment configuration, public-IP whitelist requirements, BD-09 coordinate order, quotas, cache retention, and the distinction between POI evidence and real traffic/revenue.
- [ ] **Step 4: Run backend tests, frontend build, and a local API smoke check**; record results without committing raw Baidu data or databases.
- [ ] **Step 5: Commit** with `docs: document location analysis operations` and push all commits to `origin/main`.

---

## Self-review

- The design requirements for manual input, automatic regional candidates, keyword deduplication, scoring, confidence thresholds, finance separation, fallback, quota controls, and frontend transition are covered by Tasks 1-6.
- No raw Baidu response, AK, database, upload directory, or generated frontend output is added to Git.
- API names and model fields are kept consistent across the service, schemas, and frontend client.
- The first implementation is intentionally limited to candidate centers and fixed local sampling; real rent, footfall, revenue, and storefront inventory remain outside scope.
