# Us Priser

Nightly price snapshots from 1 building-supply
chain(s) in this country, published as data files. Built for the Fixer AI estimator.

Chains: ace_us · Currency: USD ·
Auto-runs daily (cron 0 8 * * * UTC) via GitHub Actions — this repo is the database.

Data:
- `data/latest/prices.jsonl` — merged feed (all chains)
- `data/latest/<chain>.jsonl` — per-chain snapshot
- `data/latest/ages.json` — freshness ledger
- `data/latest/index.html` — human status page

Row: `{chain, country, currency, sku, ean, name, url, price, unit, in_stock, image}`

Run manually: `python3 scraper/run_daily.py` (or workflow_dispatch button).
