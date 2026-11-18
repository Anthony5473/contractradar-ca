# ContractRadar CA — Canadian Federal Expiring-Contract & Incumbent Intelligence

Automated intelligence pipeline powered by official Government of Canada (`open.canada.ca` / `canadabuys.canada.ca`) daily CSV open data.

## Architecture & Cost ($0.00 / month)
- **Ingestion:** `ingest.py` fetches `openTenderNotice` and `contractHistoryComplete` into local SQLite, deduplicating multi-amendment contracts via `ROW_NUMBER()` over `contract_num`.
- **Static Explorer & Feeds:** `build_site.py` outputs `site/index.html`, `site/data/expiring_contracts.json`, `site/data/open_tenders.json`, and `site/feed.xml` (RSS 2.0).
- **Automation:** `.github/workflows/contractradar_daily.yml` refreshes daily at 14:00 UTC for $0/mo on GitHub Actions + Cloudflare Pages/GitHub Pages.
