"""Daily automated pipeline for ContractRadar CA (ingest -> analyze -> static build)."""

from __future__ import annotations

import argparse
from pathlib import Path

from build_site import generate_static_site
from ingest import URLS, ingest_contracts_from_rows, ingest_tenders_from_rows, init_db, iter_remote_csv_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ContractRadar CA daily update")
    parser.add_argument("--db", default="prototypes/contractradar/data/contractradar.sqlite")
    parser.add_argument("--out", default="prototypes/contractradar/site")
    parser.add_argument("--max-history-rows", type=int, default=None)
    args = parser.parse_args()

    db_path = Path(args.db)
    out_dir = Path(args.out)
    conn = init_db(db_path)
    tenders_n = ingest_tenders_from_rows(conn, iter_remote_csv_rows(URLS["open_tenders"]))
    contracts_n = ingest_contracts_from_rows(
        conn, iter_remote_csv_rows(URLS["contract_history"], max_rows=args.max_history_rows)
    )
    conn.close()
    summary = generate_static_site(db_path, out_dir)
    print(f"ContractRadar daily build complete: tenders_ingested={tenders_n}, contracts_ingested={contracts_n}, summary={summary}")


if __name__ == "__main__":
    main()
