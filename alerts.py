"""Watchlist alert matcher for ContractRadar CA Pro subscribers."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

from ingest import query_expiring_contracts


def match_watchlist(
    db_path: Path,
    keywords: list[str],
    min_value: float = 50000.0,
    horizon_days: int = 180,
    as_of: dt.date | None = None,
) -> dict:
    kw_lower = [k.strip().lower() for k in keywords if k.strip()]
    conn = sqlite3.connect(db_path)
    expiring = query_expiring_contracts(conn, as_of=as_of, horizon_days=horizon_days, min_value=min_value, limit=1000)
    cur = conn.execute(
        "SELECT ref_num, title_en, closing_date, category, entity_en, notice_url_en FROM open_tenders ORDER BY closing_date ASC"
    )
    tenders = [
        dict(zip(["ref_num", "title_en", "closing_date", "category", "entity_en", "notice_url_en"], r))
        for r in cur.fetchall()
    ]
    conn.close()

    def matches(record: dict) -> bool:
        if not kw_lower:
            return True
        blob = json.dumps(record).lower()
        return any(k in blob for k in kw_lower)

    matched_expiring = [x for x in expiring if matches(x)]
    matched_tenders = [x for x in tenders if matches(x)]
    return {
        "matched_expiring": matched_expiring,
        "matched_tenders": matched_tenders,
        "expiring_count": len(matched_expiring),
        "tenders_count": len(matched_tenders),
    }


def format_digest_markdown(watchlist_name: str, digest: dict) -> str:
    lines = [
        f"# ContractRadar CA Alert Digest: {watchlist_name}",
        f"- Expiring Incumbent Contracts Matched: **{digest['expiring_count']}**",
        f"- Active Open Tenders Matched: **{digest['tenders_count']}**",
        "",
        "## Upcoming Expiring Contracts",
    ]
    for item in digest["matched_expiring"][:25]:
        lines.append(
            f"- **{item['end_date']} ({item['days_remaining']}d)** | ${item['total_value']:,.0f} | Incumbent: {item['supplier_en']} | {item['title_en']}"
        )
    lines.append("")
    lines.append("## Active Open Tenders")
    for item in digest["matched_tenders"][:25]:
        lines.append(
            f"- Closes **{item['closing_date']}** | {item['entity_en']} | {item['title_en']} ({item['notice_url_en']})"
        )
    return "\n".join(lines)
