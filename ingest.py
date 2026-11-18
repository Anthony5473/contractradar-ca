"""CanadaBuys Open Data Ingestion & SQLite Warehouse for ContractRadar CA."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import sqlite3
import urllib.request
from pathlib import Path
from typing import Iterable

DEFAULT_USER_AGENT = "curl/8.0"

URLS = {
    "new_tenders": "https://canadabuys.canada.ca/opendata/pub/newTenderNotice-nouvelAvisAppelOffres.csv",
    "open_tenders": "https://canadabuys.canada.ca/opendata/pub/openTenderNotice-ouvertAvisAppelOffres.csv",
    "contract_history": "https://canadabuys.canada.ca/opendata/pub/contractHistoryComplete-contratsOctroyesComplet.csv",
}


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS open_tenders (
            ref_num TEXT PRIMARY KEY,
            amendment TEXT,
            solicitation_num TEXT,
            title_en TEXT,
            publication_date TEXT,
            closing_date TEXT,
            status_en TEXT,
            category TEXT,
            gsin TEXT,
            gsin_desc_en TEXT,
            unspsc TEXT,
            unspsc_desc_en TEXT,
            entity_en TEXT,
            province_en TEXT,
            notice_url_en TEXT,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS contract_history (
            contract_key TEXT PRIMARY KEY,
            ref_num TEXT,
            contract_num TEXT,
            amendment TEXT,
            title_en TEXT,
            award_date TEXT,
            start_date TEXT,
            end_date TEXT,
            total_value REAL,
            currency TEXT,
            status_en TEXT,
            gsin TEXT,
            gsin_desc_en TEXT,
            unspsc TEXT,
            unspsc_desc_en TEXT,
            supplier_en TEXT,
            entity_en TEXT,
            province_en TEXT,
            updated_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_contract_end_date ON contract_history(end_date);
        CREATE INDEX IF NOT EXISTS idx_contract_value ON contract_history(total_value);
        """
    )
    conn.commit()
    return conn


def parse_float(raw: str | None) -> float:
    if not raw:
        return 0.0
    cleaned = raw.replace(",", "").replace("$", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_iso_date(raw: str | None) -> str:
    if not raw:
        return ""
    s = raw.strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return ""


def iter_remote_csv_rows(url: str, timeout: int = 60, max_rows: int | None = None) -> Iterable[dict[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text_stream = io.TextIOWrapper(resp, encoding="utf-8-sig", errors="replace", newline="")
        reader = csv.DictReader(text_stream)
        for idx, row in enumerate(reader):
            if max_rows is not None and idx >= max_rows:
                break
            yield row


def ingest_tenders_from_rows(conn: sqlite3.Connection, rows: Iterable[dict[str, str]]) -> int:
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    count = 0
    batch = []
    for r in rows:
        ref = (r.get("referenceNumber-numeroReference") or "").strip()
        if not ref:
            continue
        batch.append(
            (
                ref,
                (r.get("amendmentNumber-numeroModification") or "").strip(),
                (r.get("solicitationNumber-numeroSollicitation") or "").strip(),
                (r.get("title-titre-eng") or "").strip(),
                parse_iso_date(r.get("publicationDate-datePublication")),
                (r.get("tenderClosingDate-appelOffresDateCloture") or "").strip(),
                (r.get("tenderStatus-appelOffresStatut-eng") or "").strip(),
                (r.get("procurementCategory-categorieApprovisionnement") or "").strip(),
                (r.get("gsin-nibs") or "").strip(),
                (r.get("gsinDescription-nibsDescription-eng") or "").strip(),
                (r.get("unspsc") or "").strip(),
                (r.get("unspscDescription-eng") or "").strip(),
                (r.get("contractingEntityName-nomEntitContractante-eng") or "").strip(),
                (r.get("regionsOfDelivery-regionsLivraison-eng") or "").strip(),
                (r.get("noticeURL-avisURL-eng") or "").strip(),
                now_iso,
            )
        )
        count += 1
        if len(batch) >= 500:
            _upsert_tenders(conn, batch)
            batch.clear()
    if batch:
        _upsert_tenders(conn, batch)
    conn.commit()
    return count


def _upsert_tenders(conn: sqlite3.Connection, batch: list[tuple]) -> None:
    conn.executemany(
        """
        INSERT INTO open_tenders (
            ref_num, amendment, solicitation_num, title_en, publication_date,
            closing_date, status_en, category, gsin, gsin_desc_en, unspsc,
            unspsc_desc_en, entity_en, province_en, notice_url_en, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ref_num) DO UPDATE SET
            amendment=excluded.amendment,
            title_en=excluded.title_en,
            closing_date=excluded.closing_date,
            status_en=excluded.status_en,
            updated_at=excluded.updated_at
        """,
        batch,
    )


def ingest_contracts_from_rows(conn: sqlite3.Connection, rows: Iterable[dict[str, str]]) -> int:
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    count = 0
    batch = []
    for r in rows:
        ref = (r.get("referenceNumber-numeroReference") or "").strip()
        cnum = (r.get("contractNumber-numeroContrat") or "").strip()
        amend = (r.get("amendmentNumber-numeroModification") or "000").strip()
        key = f"{ref}|{cnum}|{amend}"
        if key == "||000":
            continue
        val = parse_float(r.get("totalContractValue-valeurTotaleContrat") or r.get("contractAmount-montantContrat"))
        end_date = parse_iso_date(r.get("contractEndDate-dateFinContrat"))
        batch.append(
            (
                key,
                ref,
                cnum,
                amend,
                (r.get("title-titre-eng") or "").strip(),
                parse_iso_date(r.get("contractAwardDate-dateAttributionContrat")),
                parse_iso_date(r.get("contractStartDate-contratDateDebut")),
                end_date,
                val,
                (r.get("contractCurrency-contratMonnaie") or "CAD").strip(),
                (r.get("contractStatus-statutContrat-eng") or "").strip(),
                (r.get("gsin-nibs") or "").strip(),
                (r.get("gsinDescription-nibsDescription-eng") or "").strip(),
                (r.get("unspsc") or "").strip(),
                (r.get("unspscDescription-eng") or "").strip(),
                (r.get("supplierLegalName-nomLegalFournisseur-eng") or "").strip(),
                (r.get("contractingEntityName-nomEntitContractante-eng") or "").strip(),
                (r.get("supplierAddressProvince-fournisseurAdresseProvince-eng") or "").strip(),
                now_iso,
            )
        )
        count += 1
        if len(batch) >= 1000:
            _upsert_contracts(conn, batch)
            batch.clear()
    if batch:
        _upsert_contracts(conn, batch)
    conn.commit()
    return count


def _upsert_contracts(conn: sqlite3.Connection, batch: list[tuple]) -> None:
    conn.executemany(
        """
        INSERT INTO contract_history (
            contract_key, ref_num, contract_num, amendment, title_en,
            award_date, start_date, end_date, total_value, currency,
            status_en, gsin, gsin_desc_en, unspsc, unspsc_desc_en,
            supplier_en, entity_en, province_en, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(contract_key) DO UPDATE SET
            end_date=excluded.end_date,
            total_value=excluded.total_value,
            status_en=excluded.status_en,
            supplier_en=excluded.supplier_en,
            updated_at=excluded.updated_at
        """,
        batch,
    )


def query_expiring_contracts(
    conn: sqlite3.Connection,
    as_of: dt.date | None = None,
    horizon_days: int = 180,
    min_value: float = 25000.0,
    limit: int = 500,
) -> list[dict]:
    ref_date = as_of or dt.date.today()
    end_limit = ref_date + dt.timedelta(days=horizon_days)
    # Deduplicate multi-amendment contracts by keeping the highest amendment per (ref_num, contract_num)
    cur = conn.execute(
        """
        WITH latest_contracts AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY COALESCE(NULLIF(contract_num, ''), ref_num)
                       ORDER BY amendment DESC, award_date DESC
                   ) AS rn
            FROM contract_history
        )
        SELECT contract_key, contract_num, amendment, title_en, end_date, total_value, currency,
               supplier_en, entity_en, province_en, gsin_desc_en, unspsc_desc_en
        FROM latest_contracts
        WHERE rn = 1
          AND end_date >= ? AND end_date <= ?
          AND total_value >= ?
          AND supplier_en != ''
        ORDER BY end_date ASC, total_value DESC
        LIMIT ?
        """,
        (ref_date.isoformat(), end_limit.isoformat(), min_value, limit),
    )
    cols = [d[0] for d in cur.description]
    results = []
    for row in cur.fetchall():
        item = dict(zip(cols, row))
        end_dt = dt.date.fromisoformat(item["end_date"])
        item["days_remaining"] = (end_dt - ref_date).days
        results.append(item)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest CanadaBuys open data into SQLite")
    parser.add_argument("--db", default="prototypes/contractradar/data/contractradar.sqlite")
    parser.add_argument("--max-history-rows", type=int, default=None)
    args = parser.parse_args()

    conn = init_db(Path(args.db))
    t_count = ingest_tenders_from_rows(conn, iter_remote_csv_rows(URLS["open_tenders"]))
    c_count = ingest_contracts_from_rows(
        conn, iter_remote_csv_rows(URLS["contract_history"], max_rows=args.max_history_rows)
    )
    expiring = query_expiring_contracts(conn)
    print(f"Ingested open_tenders={t_count}, contract_history={c_count}, expiring_180d={len(expiring)}")


if __name__ == "__main__":
    main()
