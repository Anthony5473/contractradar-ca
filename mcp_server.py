"""Stdio JSON-RPC 2.0 MCP Server exposing ContractRadar CA SQLite procurement intelligence."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parent / "data" / "contractradar.sqlite"


def search_expiring_contracts(
    db_path: Path,
    keyword: str = "",
    horizon_days: int = 180,
    min_value: float = 25000.0,
    limit: int = 20,
    as_of: dt.date | None = None,
) -> list[dict[str, Any]]:
    ref_date = as_of or dt.date.today()
    end_limit = ref_date + dt.timedelta(days=horizon_days)
    kw = f"%{keyword.strip().lower()}%"
    conn = sqlite3.connect(db_path)
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
        SELECT contract_num, title_en, end_date, total_value, currency,
               supplier_en, entity_en, gsin_desc_en, unspsc_desc_en
        FROM latest_contracts
        WHERE rn = 1
          AND end_date >= ? AND end_date <= ?
          AND total_value >= ?
          AND supplier_en != ''
          AND (
              ? = '%%'
              OR LOWER(title_en) LIKE ?
              OR LOWER(supplier_en) LIKE ?
              OR LOWER(entity_en) LIKE ?
              OR LOWER(gsin_desc_en) LIKE ?
              OR LOWER(unspsc_desc_en) LIKE ?
          )
        ORDER BY end_date ASC, total_value DESC
        LIMIT ?
        """,
        (ref_date.isoformat(), end_limit.isoformat(), min_value, kw, kw, kw, kw, kw, kw, limit),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return rows


def search_open_tenders(db_path: Path, keyword: str = "", limit: int = 20) -> list[dict[str, Any]]:
    kw = f"%{keyword.strip().lower()}%"
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        """
        SELECT ref_num, title_en, closing_date, category, entity_en, province_en, notice_url_en
        FROM open_tenders
        WHERE ? = '%%'
           OR LOWER(title_en) LIKE ?
           OR LOWER(entity_en) LIKE ?
           OR LOWER(gsin_desc_en) LIKE ?
           OR LOWER(unspsc_desc_en) LIKE ?
        ORDER BY closing_date ASC
        LIMIT ?
        """,
        (kw, kw, kw, kw, kw, limit),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return rows


def handle_rpc_request(req: dict[str, Any], db_path: Path = DEFAULT_DB) -> dict[str, Any] | None:
    req_id = req.get("id")
    method = req.get("method", "")
    params = req.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "contractradar-ca", "version": "0.1.0"},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "search_expiring_contracts",
                        "description": "Search upcoming expiring Canadian federal contracts and incumbent vendors from CanadaBuys data.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "keyword": {"type": "string"},
                                "horizon_days": {"type": "integer", "default": 180},
                                "min_value": {"type": "number", "default": 25000},
                                "limit": {"type": "integer", "default": 20},
                            },
                        },
                    },
                    {
                        "name": "search_open_tenders",
                        "description": "Search active Canadian federal open tenders on CanadaBuys.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "keyword": {"type": "string"},
                                "limit": {"type": "integer", "default": 20},
                            },
                        },
                    },
                ]
            },
        }
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "search_expiring_contracts":
            data = search_expiring_contracts(
                db_path=db_path,
                keyword=args.get("keyword", ""),
                horizon_days=int(args.get("horizon_days", 180)),
                min_value=float(args.get("min_value", 25000)),
                limit=int(args.get("limit", 20)),
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]},
            }
        if name == "search_open_tenders":
            data = search_open_tenders(
                db_path=db_path,
                keyword=args.get("keyword", ""),
                limit=int(args.get("limit", 20)),
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]},
            }
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown tool: {name}"}}

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main() -> None:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        resp = handle_rpc_request(req, db_path=db_path)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
