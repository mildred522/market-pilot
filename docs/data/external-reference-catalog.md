# External Reference Data Catalog

## Purpose

Reference datasets provide city-wide and category-wide context for restaurant
analysis. They are background evidence, not a replacement for point-level POI,
rent, footfall, route, delivery, or competitor observations.

## Storage and Selection

- City data: `backend/data/reference/cities/<city>/<effective-year>.json`
- Category data: `backend/data/reference/categories/<category>/<effective-year>.json`
- Selection is exact by slug and year. The repository does not silently fall
  back to another year.
- Every metric declares `value`, `unit`, `period`, `source_ids`, `status`, and
  an optional definition or qualifier.

## Metric Status

| Status | Meaning |
| --- | --- |
| `reported` | A published administrative or measured value |
| `estimated` | A historical value estimated by a research method |
| `forecast` | A value that was future-facing at publication time |
| `derived` | A value calculated by this project from cited inputs |

A forecast remains a forecast after its target year has passed unless a source
publishes a measured or retrospective estimate.

## Source Hierarchy

1. Government statistics for city population, economy, consumption, transport,
   and education.
2. Industry association and platform research for category structure and
   platform-observed trends.
3. Listed-company filings for disclosed commercial-research estimates.
4. Commercial research only when its method and definition are explicit.

Lower-ranked sources do not override a higher-ranked source with the same
definition and period. Sources with different definitions remain separate.

## Chengdu 2025-Effective Baseline

File: `backend/data/reference/cities/chengdu/2025.json`

Primary source: Chengdu Municipal Bureau of Statistics and NBS Chengdu Survey
Office, *2024 Chengdu Statistical Bulletin*, published 2025-03-28:

https://cdstats.chengdu.gov.cn/cdstjj/c154795/2026-04/14/58dc076a80974f999828b691bfca027f/files/0cac2cb9ed15430dac5a694530fdd8a4.pdf

The baseline covers resident population, urbanization, GDP, service-sector
share, retail sales, food-service revenue, online food-service growth for
above-quota enterprises, university students, and metro passenger trips.

The values describe Chengdu as a whole. A report must not convert them directly
into site traffic, expected orders, rent tolerance, or competitor density.

## Milk-Tea 2025-Effective Baseline

File: `backend/data/reference/categories/milk-tea/2025.json`

Sources:

- CCFA and Meituan, *2023 New Tea Beverage Research Report*:
  https://www.meituan.com/news/NN230921068001140
- SAMR consumer guidance for made-to-order drinks:
  https://www.samr.gov.cn/spcjs/yjjl/art/2023/art_da5490e8dcdc446e85313878b3ba8f69.html
- HKEX, Mixue Group prospectus industry overview:
  https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0221/11543479/2025022100055_c.pdf

### Definition Warning

The CCFA/Meituan report's `new tea beverage consumption market` and the HKEX
filing's `made-to-order tea shop terminal retail market` are different market
definitions. Their values must not be added, divided, or used as the endpoints
of one growth calculation.

The CCFA report was published in September 2023. Its full-year 2023 market
value was future-facing at publication and is therefore stored as `forecast`,
not `reported`. The HKEX filing attributes its historical market figures to
commercial research, so they are stored as `estimated`.

## Agent Usage Rules

- Cite the metric's source, period, status, and unit in generated evidence.
- Use forecasts as trend context, never as observed local demand.
- Show dataset limitations when reference metrics materially affect a score.
- Prefer fresh Baidu point-level observations for local competition and access.
- Continue with a degraded-data warning when an exact reference dataset is
  unavailable.

## Update Procedure

1. Add a new year file instead of overwriting a prior baseline.
2. Keep source URLs public and use a stable publication URL where possible.
3. Preserve the source's original definition and publication-time status.
4. Run the contract, repository, production reference, and full backend tests.
5. Review material definition changes before comparing metrics across years.
