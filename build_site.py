"""Static Explorer, JSON Feeds, and RSS 2.0 Generator for ContractRadar CA."""

from __future__ import annotations

import datetime as dt
import html
import json
import sqlite3
from pathlib import Path

from ingest import query_expiring_contracts


def build_rss_feed(expiring: list[dict], base_url: str = "https://anthony5473.github.io/contractradar-ca") -> str:
    now_rfc = dt.datetime.now(dt.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    items_xml = []
    for item in expiring[:50]:
        title = html.escape(
            f"[{item['end_date']}] {item['title_en'] or 'Federal Contract'} (${item['total_value']:,.0f} - {item['supplier_en']})"
        )
        desc = html.escape(
            f"Incumbent: {item['supplier_en']} | Buyer: {item['entity_en']} | Category: {item['unspsc_desc_en'] or item['gsin_desc_en']} | Days left: {item['days_remaining']}"
        )
        guid = html.escape(item["contract_key"])
        items_xml.append(
            f"    <item>\n      <title>{title}</title>\n      <link>{base_url}/#/{guid}</link>\n      <guid isPermaLink=\"false\">{guid}</guid>\n      <description>{desc}</description>\n    </item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n  <channel>\n'
        "    <title>ContractRadar CA — Expiring Federal Contracts</title>\n"
        f"    <link>{base_url}</link>\n"
        "    <description>Canadian federal contracts expiring within 180 days from official CanadaBuys Open Data.</description>\n"
        f"    <lastBuildDate>{now_rfc}</lastBuildDate>\n"
        + "\n".join(items_xml)
        + "\n  </channel>\n</rss>\n"
    )


def generate_static_site(
    db_path: Path,
    out_dir: Path,
    as_of: dt.date | None = None,
    base_url: str = "https://anthony5473.github.io/contractradar-ca",
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    expiring = query_expiring_contracts(conn, as_of=as_of, horizon_days=180, min_value=25000.0, limit=500)
    cur = conn.execute(
        "SELECT ref_num, title_en, closing_date, category, entity_en, notice_url_en FROM open_tenders ORDER BY closing_date ASC LIMIT 250"
    )
    tenders = [
        dict(zip(["ref_num", "title_en", "closing_date", "category", "entity_en", "notice_url_en"], r))
        for r in cur.fetchall()
    ]
    conn.close()

    total_expiring_value = sum(item["total_value"] for item in expiring)
    summary = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "expiring_count": len(expiring),
        "open_tenders_count": len(tenders),
        "total_expiring_value": round(total_expiring_value, 2),
    }

    (data_dir / "expiring_contracts.json").write_text(json.dumps(expiring, indent=2), encoding="utf-8")
    (data_dir / "open_tenders.json").write_text(json.dumps(tenders, indent=2), encoding="utf-8")
    (data_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "feed.xml").write_text(build_rss_feed(expiring, base_url=base_url), encoding="utf-8")
    (out_dir / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {base_url}/sitemap.xml\n", encoding="utf-8")

    categories = [
        ("it-software-cyber", "IT, Software & Cybersecurity", ["software", "it ", "cyber", "cloud", "system", "network", "data", "security"]),
        ("construction-trades", "Construction, Trades & Facilities", ["construction", "hvac", "plumbing", "electrical", "repair", "building", "roof", "maintenance"]),
        ("engineering-consulting", "Engineering & Professional Services", ["engineering", "consulting", "architect", "research", "audit", "advisory", "management"]),
    ]
    cat_dir = out_dir / "categories"
    cat_dir.mkdir(parents=True, exist_ok=True)
    sitemap_urls = [f"{base_url}/"]
    cat_links_html = []
    for slug, label, kws in categories:
        matched = [
            x
            for x in expiring
            if any(k in f"{x.get('title_en','')} {x.get('gsin_desc_en','')} {x.get('unspsc_desc_en','')}".lower() for k in kws)
        ]
        rows_html = "\n".join(
            f"<tr><td>{html.escape(x['end_date'])}</td><td>{x['days_remaining']}d</td><td>{html.escape(x['title_en'])}</td><td>{html.escape(x['supplier_en'])}</td><td>{html.escape(x['entity_en'])}</td><td>${x['total_value']:,.0f}</td></tr>"
            for x in matched[:100]
        )
        cat_html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Expiring Canadian Federal {html.escape(label)} Contracts | ContractRadar CA</title>
<style>body{{font-family:system-ui,sans-serif;margin:0;background:#f8fafc;color:#0f172a}}header{{background:#0f2942;color:#fff;padding:18px 24px}}main{{max-width:1100px;margin:24px auto;padding:0 18px}}table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid #cbd5e1;font-size:13px}}th,td{{padding:9px;border-bottom:1px solid #e2e8f0;text-align:left}}th{{background:#f1f5f9}}</style>
</head><body><header><a href="../index.html" style="color:#7dd3fc;text-decoration:none;">&larr; All Expiring Contracts</a><h1 style="margin:6px 0 0;font-size:20px;">Expiring Federal Contracts: {html.escape(label)} ({len(matched)})</h1></header>
<main><table><thead><tr><th>End Date</th><th>Days Left</th><th>Title</th><th>Incumbent</th><th>Buyer</th><th>Value (CAD)</th></tr></thead><tbody>{rows_html}</tbody></table></main></body></html>"""
        (cat_dir / f"{slug}.html").write_text(cat_html, encoding="utf-8")
        sitemap_urls.append(f"{base_url}/categories/{slug}.html")
        cat_links_html.append(f'<a href="categories/{slug}.html" style="margin-right:12px;color:#0284c7;font-size:13px;font-weight:600;">{html.escape(label)} ({len(matched)})</a>')

    sitemap_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(f"  <url><loc>{u}</loc></url>" for u in sitemap_urls)
        + "\n</urlset>\n"
    )
    (out_dir / "sitemap.xml").write_text(sitemap_xml, encoding="utf-8")

    html_page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ContractRadar CA — Canadian Federal Expiring Contract & Incumbent Explorer</title>
  <meta name="description" content="Track Canadian federal contracts expiring in the next 180 days, incumbent vendors, and active open tenders powered by CanadaBuys Open Data." />
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 0; background: #f8fafc; color: #0f172a; }}
    header {{ background: #0f2942; color: #fff; padding: 20px 24px; }}
    main {{ max-width: 1120px; margin: 24px auto; padding: 0 18px 48px; }}
    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 18px; }}
    .stat {{ background: #fff; border: 1px solid #cbd5e1; border-radius: 8px; padding: 14px; }}
    .stat strong {{ font-size: 22px; display: block; color: #0f2942; }}
    .tabs {{ display: flex; gap: 8px; margin-bottom: 12px; }}
    .tab {{ padding: 8px 14px; border: 1px solid #cbd5e1; border-radius: 6px; background: #fff; cursor: pointer; font-weight: 600; }}
    .tab.active {{ background: #0f2942; color: #fff; border-color: #0f2942; }}
    input {{ width: 100%; max-width: 460px; padding: 10px; border: 1px solid #cbd5e1; border-radius: 6px; margin-bottom: 14px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #cbd5e1; font-size: 13px; }}
    th, td {{ padding: 10px; border-bottom: 1px solid #e2e8f0; text-align: left; }}
    th {{ background: #f1f5f9; }}
  </style>
</head>
<body>
  <header>
    <h1 style="margin:0;font-size:22px;">ContractRadar CA — Expiring Federal Contracts &amp; Incumbent Intelligence</h1>
    <p style="margin:4px 0 0;opacity:0.85;font-size:14px;">Powered by Official Government of Canada (CanadaBuys) Open Data &bull; <a href="feed.xml" style="color:#7dd3fc;">RSS Feed</a></p>
  </header>
  <main>
    <div class="stats">
      <div class="stat"><span>Expiring &le; 180 Days</span><strong>{summary['expiring_count']}</strong></div>
      <div class="stat"><span>Total Renewal Value</span><strong>${summary['total_expiring_value']:,.0f} CAD</strong></div>
      <div class="stat"><span>Active Open Tenders</span><strong>{summary['open_tenders_count']}</strong></div>
    </div>
    <div class="tabs">
      <button id="tabExp" class="tab active" type="button">Expiring Contracts (&le;180d)</button>
      <button id="tabTen" class="tab" type="button">Active Open Tenders</button>
    </div>
    <div style="margin-bottom:12px;">{"".join(cat_links_html)}</div>
    <input id="q" type="search" placeholder="Filter by keyword, incumbent supplier, buyer, or category..." />
    <table>
      <thead id="thead"></thead>
      <tbody id="rows"></tbody>
    </table>
  </main>
  <script>
    Promise.all([
      fetch('data/expiring_contracts.json').then(r => r.json()),
      fetch('data/open_tenders.json').then(r => r.json())
    ]).then(([expiring, tenders]) => {{
      let mode = 'expiring';
      const thead = document.getElementById('thead');
      const tbody = document.getElementById('rows');
      const input = document.getElementById('q');
      const tabExp = document.getElementById('tabExp');
      const tabTen = document.getElementById('tabTen');

      const render = () => {{
        const q = (input.value || '').toLowerCase();
        if (mode === 'expiring') {{
          thead.innerHTML = '<tr><th>End Date</th><th>Days Left</th><th>Title</th><th>Incumbent Supplier</th><th>Buyer</th><th>Value (CAD)</th></tr>';
          const filtered = expiring.filter(x => !q || JSON.stringify(x).toLowerCase().includes(q)).slice(0, 100);
          tbody.innerHTML = filtered.map(x => `<tr>
            <td>${{x.end_date}}</td>
            <td>${{x.days_remaining}}d</td>
            <td>${{x.title_en}}</td>
            <td>${{x.supplier_en}}</td>
            <td>${{x.entity_en}}</td>
            <td>$${{Number(x.total_value).toLocaleString()}}</td>
          </tr>`).join('');
        }} else {{
          thead.innerHTML = '<tr><th>Closing</th><th>Category</th><th>Title</th><th>Buyer</th><th>Link</th></tr>';
          const filtered = tenders.filter(x => !q || JSON.stringify(x).toLowerCase().includes(q)).slice(0, 100);
          tbody.innerHTML = filtered.map(x => `<tr>
            <td>${{x.closing_date}}</td>
            <td>${{x.category}}</td>
            <td>${{x.title_en}}</td>
            <td>${{x.entity_en}}</td>
            <td>${{x.notice_url_en ? `<a href="${{x.notice_url_en}}" target="_blank" rel="noopener">CanadaBuys</a>` : ''}}</td>
          </tr>`).join('');
        }}
      }};

      tabExp.addEventListener('click', () => {{ mode = 'expiring'; tabExp.classList.add('active'); tabTen.classList.remove('active'); render(); }});
      tabTen.addEventListener('click', () => {{ mode = 'tenders'; tabTen.classList.add('active'); tabExp.classList.remove('active'); render(); }});
      input.addEventListener('input', render);
      render();
    }});
  </script>
</body>
</html>
"""
    (out_dir / "index.html").write_text(html_page, encoding="utf-8")
    return summary
