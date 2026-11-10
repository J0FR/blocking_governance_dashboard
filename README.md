# Block support dashboard

Two tools in one dashboard, to understand what blocking drivers costs and whether blocked drivers come back.

- **Block calculator** – upload a list of blocked drivers (`driver_id`, `block_hours`; `9999` = permanent) and, using the
  28-day driver base, see the loss in trips, TSH, GMV and net economic value (GMV minus the CX cost avoided), by
  country, city and driver, over a fixed 180-day horizon, plus how much of it the rest of each city can absorb.
- **Block impact & retention** – upload the result of the block-impact and retention queries:
  - *Impact of blocks*: rows = the rule behind the block, columns = MX, AR, CO, Rest of SSL and All SSL, with volume and
    share of the region (impacted drivers, active drivers, trips, TSH).
  - *Retention*: rows = measure (`category_four_name`), columns = retention windows 1–12,
    value = `returned_drivers_general / eligible_drivers_general`.

Every upload bar has a **Copy query** button: the SQL comes with the real dates already in it (no parameters), so it can
be run as is on your side and the resulting CSV uploaded back.

## Layout

```
backend/    FastAPI + pandas (app/main.py, impact.py, block_impact.py, snapshot.py, sql/*.sql, tests/)
frontend/   Next.js 16 + React 19 + Tailwind 4 + Recharts
sample_data/SYNTHETIC_*.csv   fake outputs shaped like the two queries, to try the uploads
```

## Run it

```bash
# backend (Python 3.11+)
pip install fastapi "uvicorn[standard]" python-multipart pandas numpy pyarrow python-dotenv pytest
cd backend
python -m uvicorn app.main:app --port 8000 --reload --reload-dir app --timeout-graceful-shutdown 3

# frontend
cd frontend
npm install
npm run dev        # http://localhost:3000   (API url: NEXT_PUBLIC_API_URL, default http://localhost:8000)
```

Tests: `cd backend && python -m pytest tests`. Frontend checks: `npx tsc --noEmit && npx eslint app components lib`.

## Notes

- Uploaded data is stored in `backend/data/` (git-ignored). Nothing real is committed.
- The driver base has IPT in local currency; it is converted to USD with `backend/app/fx_rates.json`. **The rates in that
  file are approximate placeholders**: replace them with the finance rates.
- The queries count distinct drivers per week/city/rule, so totals across rows are driver-weeks, not de-duplicated drivers.
- `.env` (see `.env.example`) is only needed to run queries from this machine; the dashboard works with uploaded CSVs.
