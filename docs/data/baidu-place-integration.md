# Baidu Place API Integration

## Scope

The MVP uses Baidu Place API 2.0 circle search to collect nearby restaurant
POI context. It does not treat POI results as measured footfall, orders,
revenue, delivery volume, rent, or store survival.

Official circle-search documentation:

https://lbsyun.baidu.com/docs/webapi?title=placev2%2Fguide%2Fwebservice-placeapi%2Fcircle

Weather, walking routes, pagination beyond the first page, and live credential
smoke tests are separate work.

## Runtime Configuration

Create a Baidu Maps server-side application and expose its key to the backend:

```powershell
$env:BAIDU_MAP_AK = "<server-side-ak>"
```

The key must remain in backend runtime configuration. Do not put it in React
code, API responses, snapshots, fixtures, logs, or committed environment files.
Configure a server IP allowlist in the Baidu console when the deployment has a
stable outbound IP.

## Request Contract

`BaiduMapClient.search_nearby()` sends:

| Parameter | Value |
| --- | --- |
| `query` | Category search term, such as `奶茶` |
| `location` | `latitude,longitude` |
| `radius` | Radius in meters |
| `radius_limit` | `true` |
| `output` | `json` |
| `scope` | `2` for detail fields |
| `filter` | `industry_type:cater` |
| `coord_type` | `3`, BD-09 latitude/longitude |
| `page_size` | `20`, provider maximum per keyword |
| `page_num` | `0`, first page |

Input coordinates must be BD-09 latitude/longitude. Passing WGS-84 or GCJ-02
coordinates as BD-09 can shift the search center and invalidate the comparison.

## Normalized DTO

The client retains only:

- POI UID and name
- latitude and longitude
- address and business status
- distance from the search center
- category tag and brand
- overall rating, comment count, and average price

Baidu returns several numeric detail fields as strings. The client converts
valid values to numbers and converts empty or invalid values to `None`.

## Provider Limits

- A single page returns at most 20 POIs per keyword.
- The provider's `total` value is capped at 150 for data-protection reasons.
- `scope=2` detail fields vary by POI type and may be absent.
- `radius_limit=true` strictly constrains the requested radius but can affect
  the number of POIs returned on a page and `total` accuracy.
- POI status, images, and some other fields can require advanced permission.

The analyzer therefore keeps provider total and sampled fields separate,
calculates a data-completeness ratio, and emits warnings for first-page
sampling and the 150-result cap.

## Competition Metrics

The deterministic analyzer produces:

- provider competitor total
- active sampled competitor count
- average sampled rating and price
- sampled brand ratio
- median sampled distance
- sampled field completeness
- competition pressure score

The pressure score is:

```text
min(total, 40) / 40 * 60
+ sampled_brand_ratio * 20
+ sampled_average_rating / 5 * 20
```

The result is rounded to one decimal and capped at 100. It is a transparent
comparison heuristic, not a probability of store success.

## Persistence Boundary

Raw provider JSON exists only inside the client request call. The client returns
normalized DTOs, the analyzer returns `ExternalContextData`, and the snapshot
service persists calculated metrics, compact evidence, and warnings.

Persisted evidence includes query, BD-09 center, radius, provider total, sample
count, observation time, and expiry time. It excludes raw `results`, the AK,
photos, telephone numbers, and the full provider response.

## Degraded Behavior

- Missing `BAIDU_MAP_AK`: configuration error before a request is sent.
- Nonzero Baidu status: provider error with status and message.
- Missing detail fields: nullable normalized fields and lower completeness.
- No active POIs: metrics remain explicit and a warning is emitted.
- Provider unavailable: the later orchestration layer should continue with
  versioned city/category references and a degraded-data warning.
