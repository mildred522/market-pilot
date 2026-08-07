# Location Analysis Operations

## Local Services

Run the backend from `backend`:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run the frontend from `frontend`:

```powershell
npm run dev -- --hostname 127.0.0.1 --port 3000
```

The browser entry point is `http://127.0.0.1:3000/pre-open`.

## Baidu Configuration

The backend reads `BAIDU_MAP_AK` from the process environment. The AK must remain on the server side. The Baidu server application must allow the current public egress IP, which may differ from the machine's private address when a proxy, VPN, NAT, or split tunnel is active.

The location API uses BD-09 latitude,longitude coordinates. A missing AK returns a configuration error. IP restrictions, signature failures, permissions, and quota exhaustion are returned as classified provider errors and are not silently retried.

## Data Boundaries

Baidu POIs are external evidence for competition, demand-proxy signals, transport, and surrounding amenities. They are not measured footfall, orders, revenue, rent, survival rate, or a probability of success. The service stores normalized metrics, evidence scope, observation time, expiry, and warnings; it does not store raw provider payloads.

POI snapshots are reusable for seven days only when the full query scope matches, including keywords, classifications, radius, pagination, provider filters, coordinate type, and scoring version. A partial radius request marks unobserved outer rings and reduces confidence.

## Real Smoke Test

The real Baidu test is opt-in and never runs in the default suite:

```powershell
$env:RUN_BAIDU_SMOKE = "1"
$env:BAIDU_MAP_AK = "<server AK>"
python -m pytest -q backend/tests/test_location_real_smoke.py
```

Before running it, add the actual public egress IP shown by the provider to the Baidu server application's IP whitelist. Do not commit the AK, response payload, SQLite database, or smoke-test output.
