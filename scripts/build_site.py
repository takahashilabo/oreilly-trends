#!/usr/bin/env python3
"""
Build index.html from data/pool/<date>.json (fetched from the browser via
Claude in Chrome: one pool sorted by popularity, one sorted by publication date).

Usage:
  python3 scripts/build_site.py            # use the latest pool file
  python3 scripts/build_site.py 2026-09-23  # use a specific date
"""
import html
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
POOL_DIR = DATA_DIR / "pool"
HISTORY_DIR = DATA_DIR / "history"
INDEX_HTML = ROOT / "index.html"

TOP_N = 50

VIEWS = {
    "all": {"label": "All time", "months": None},
    "m1": {"label": "Last month", "months": 1},
    "m3": {"label": "Last 3 months", "months": 3},
    "m6": {"label": "Last 6 months", "months": 6},
}


def load_pools(date: str | None):
    if date:
        f = POOL_DIR / f"{date}.json"
        if not f.exists():
            sys.exit(f"[ERROR] {f} not found.")
    else:
        files = sorted(POOL_DIR.glob("20*-*-*.json"))
        if not files:
            sys.exit("[ERROR] No files in data/pool/. Fetch data from the browser first.")
        f = files[-1]
        date = f.stem
    with open(f, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    pop_pool = data["pop_pool"]
    recency_pool = data["recency_pool"]
    for b in pop_pool + recency_pool:
        b["issued_year"] = (b.get("issued") or "")[:4]
    return date, pop_pool, recency_pool


def parse_issued(b):
    if not b.get("issued"):
        return None
    try:
        return datetime.fromisoformat(b["issued"].replace("Z", "+00:00"))
    except ValueError:
        return None


def build_view(pop_pool: list[dict], recency_pool: list[dict], months: int | None):
    if months is None:
        # 全期間: popularity順そのままのプールを使う
        candidates = pop_pool
    else:
        # 直近Nヶ月: publication_date順プールから「出版済み・期間内」の本を集め、
        # その中でpopularityスコアが高い順に並べ直す
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=months * 30.44)
        window = []
        for b in recency_pool:
            issued_dt = parse_issued(b)
            if issued_dt is None or issued_dt > now or issued_dt < cutoff:
                continue  # 未来日(早期リリース予定)や期間外を除外
            window.append(b)
        candidates = sorted(window, key=lambda b: b.get("popularity") or 0, reverse=True)

    top = candidates[:TOP_N]
    out = []
    for i, b in enumerate(top, start=1):
        nb = dict(b)
        nb["rank"] = i
        out.append(nb)
    return out, len(candidates)


def load_prev_ranks(view_key: str, today: str):
    hist_file = HISTORY_DIR / f"{view_key}.json"
    if not hist_file.exists():
        return {}, {}, None
    with open(hist_file, "r", encoding="utf-8") as f:
        history = json.load(f)
    dates = sorted({d for entry in history.values() for d in entry["ranks"] if d != today})
    if not dates:
        return {}, {}, None
    prev_date = dates[-1]
    prev_ranks = {aid: entry["ranks"][prev_date] for aid, entry in history.items() if prev_date in entry["ranks"]}
    prev_titles = {aid: (entry["title"], entry.get("path")) for aid, entry in history.items() if prev_date in entry["ranks"]}
    return prev_ranks, prev_titles, prev_date


def update_history(view_key: str, today: str, books: list[dict]):
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    hist_file = HISTORY_DIR / f"{view_key}.json"
    history = {}
    if hist_file.exists():
        with open(hist_file, "r", encoding="utf-8") as f:
            history = json.load(f)
    for b in books:
        aid = b["archive_id"]
        entry = history.setdefault(aid, {"title": b["title"], "ranks": {}})
        entry["title"] = b["title"]
        entry["path"] = b.get("web_path")
        entry["ranks"][today] = b["rank"]
    with open(hist_file, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def change_badge(book, prev_ranks):
    prev = prev_ranks.get(book["archive_id"])
    if prev is None:
        return '<span class="badge new">NEW</span>'
    diff = prev - book["rank"]
    if diff > 0:
        return f'<span class="badge up">▲{diff}</span>'
    if diff < 0:
        return f'<span class="badge down">▼{-diff}</span>'
    return '<span class="badge flat">-</span>'


def book_link(title, path, archive_id):
    url = "https://learning.oreilly.com" + (path or f"/library/view/-/{archive_id}/")
    return f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{html.escape(title)}</a>'


def compute_movers(books, prev_ranks, prev_titles, top_k=6):
    """前回との差分から、上昇/下降/新登場/圏外のハイライトを作る"""
    current_ids = {b["archive_id"] for b in books}

    gains, losses = [], []
    for b in books:
        prev = prev_ranks.get(b["archive_id"])
        if prev is None:
            continue
        diff = prev - b["rank"]
        if diff > 0:
            gains.append((book_link(b["title"], b.get("web_path"), b["archive_id"]), diff))
        elif diff < 0:
            losses.append((book_link(b["title"], b.get("web_path"), b["archive_id"]), -diff))
    gains.sort(key=lambda x: -x[1])
    losses.sort(key=lambda x: -x[1])

    new_entries = [book_link(b["title"], b.get("web_path"), b["archive_id"]) for b in books if b["archive_id"] not in prev_ranks]
    dropped = [
        (book_link(*prev_titles[aid], aid), rank)
        for aid, rank in prev_ranks.items()
        if aid not in current_ids
    ]
    dropped.sort(key=lambda x: x[1])  # 前回上位だったものを優先表示

    return {
        "gains": gains[:top_k],
        "losses": losses[:top_k],
        "new": new_entries[:top_k],
        "dropped": [t for t, _ in dropped[:top_k]],
    }


def render_movers(movers, prev_date):
    if prev_date is None:
        return '<div class="movers-empty">First run — nothing to compare yet. Changes will show up here from the next run onward.</div>'

    groups = []
    if movers["gains"]:
        chips = "".join(f'<span class="chip up">{t} <b>▲{d}</b></span>' for t, d in movers["gains"])
        groups.append(f'<div class="movers-row"><span class="movers-label">📈 Gainers</span>{chips}</div>')
    if movers["losses"]:
        chips = "".join(f'<span class="chip down">{t} <b>▼{d}</b></span>' for t, d in movers["losses"])
        groups.append(f'<div class="movers-row"><span class="movers-label">📉 Losers</span>{chips}</div>')
    if movers["new"]:
        chips = "".join(f'<span class="chip new">{t}</span>' for t in movers["new"])
        groups.append(f'<div class="movers-row"><span class="movers-label">🆕 New entries</span>{chips}</div>')
    if movers["dropped"]:
        chips = "".join(f'<span class="chip out">{t}</span>' for t in movers["dropped"])
        groups.append(f'<div class="movers-row"><span class="movers-label">📤 Dropped out</span>{chips}</div>')

    if not groups:
        return '<div class="movers-empty">No change since last time.</div>'
    return '<div class="movers">' + "".join(groups) + '</div>'


def render_rows(books, prev_ranks):
    rows = []
    for b in books:
        authors = ", ".join(b.get("authors", [])[:3])
        publishers = ", ".join(b.get("publishers", [])[:1])
        topics = " / ".join(b.get("topics", []))
        rating = f'{b["average_rating"]/1000:.1f}' if isinstance(b.get("average_rating"), (int, float)) else "-"
        web_url = "https://learning.oreilly.com" + (b.get("web_path") or "")
        rows.append(f"""
        <tr>
          <td class="rank">{b['rank']}</td>
          <td class="change">{change_badge(b, prev_ranks)}</td>
          <td class="title">
            <a href="{web_url}" target="_blank" rel="noopener">{b['title']}</a>
            <div class="meta">{authors} ・ {publishers} ・ {b['issued_year']}</div>
            <div class="topics">{topics}</div>
          </td>
          <td class="rating">{rating}</td>
          <td class="reviews">{b.get('number_of_reviews') or 0}</td>
        </tr>""")
    return "".join(rows)


def render_html(today: str, view_data: dict):
    tabs_nav = "".join(
        f'<button class="tab-btn{" active" if k == "all" else ""}" data-tab="{k}">{v["meta"]["label"]}</button>'
        for k, v in view_data.items()
    )
    tabs_panels = "".join(
        f"""
        <div class="tab-panel{' active' if k == 'all' else ''}" id="panel-{k}">
          <div class="sub">{v['meta']['note']}</div>
          {v['movers_html']}
          <table>
            <thead><tr><th>#</th><th>Change</th><th>Title</th><th class="rating">Rating</th><th class="reviews">Reviews</th></tr></thead>
            <tbody>{v['rows']}</tbody>
          </table>
        </div>"""
        for k, v in view_data.items()
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>O'Reilly Learning Top Books</title>
<style>
  :root {{
    --bg: #f7f7f5; --card: #ffffff; --text: #1a1a1a; --sub: #666;
    --border: #e5e5e0; --accent: #d32f2f;
    --up: #1e8e3e; --down: #d93025; --new: #1a73e8; --flat: #999;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 0 16px 60px;
    background: var(--bg); color: var(--text);
    font-family: -apple-system, "Hiragino Sans", "Yu Gothic", sans-serif;
  }}
  .wrap {{ max-width: 900px; margin: 0 auto; }}
  header {{ padding: 32px 0 16px; }}
  h1 {{ font-size: 22px; margin: 0 0 6px; }}
  .sub {{ color: var(--sub); font-size: 13px; margin: 4px 0 14px; }}
  .tabs {{ display: flex; gap: 6px; margin-bottom: 4px; flex-wrap: wrap; }}
  .tab-btn {{
    border: 1px solid var(--border); background: var(--card); color: var(--sub);
    padding: 8px 14px; border-radius: 8px 8px 0 0; font-size: 13px; font-weight: 600;
    cursor: pointer;
  }}
  .tab-btn.active {{ background: var(--text); color: #fff; border-color: var(--text); }}
  .tab-panel {{ display: none; }}
  .tab-panel.active {{ display: block; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card);
    border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); font-size: 14px; }}
  th {{ background: #fafaf8; font-size: 12px; color: var(--sub); text-transform: uppercase; letter-spacing: .03em; }}
  td.rank {{ font-weight: 700; font-size: 16px; width: 36px; }}
  td.change {{ width: 60px; }}
  td.rating, td.reviews {{ width: 60px; color: var(--sub); }}
  .meta {{ color: var(--sub); font-size: 12px; margin-top: 2px; }}
  .topics {{ color: #888; font-size: 11px; margin-top: 2px; }}
  a {{ color: var(--text); text-decoration: none; font-weight: 600; }}
  a:hover {{ color: var(--accent); text-decoration: underline; }}
  .badge {{ display: inline-block; font-size: 12px; font-weight: 700; padding: 2px 6px; border-radius: 6px; }}
  .badge.up {{ color: var(--up); background: #e6f4ea; }}
  .badge.down {{ color: var(--down); background: #fce8e6; }}
  .badge.new {{ color: var(--new); background: #e8f0fe; }}
  .badge.flat {{ color: var(--flat); background: #f1f1f0; }}
  tr:last-child td {{ border-bottom: none; }}
  .movers {{ margin-bottom: 14px; display: flex; flex-direction: column; gap: 6px; }}
  .movers-row {{ display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 12px; }}
  .movers-label {{ font-weight: 700; color: var(--sub); margin-right: 2px; white-space: nowrap; }}
  .chip {{ display: inline-flex; align-items: center; gap: 4px; padding: 3px 8px; border-radius: 999px; background: var(--card); border: 1px solid var(--border); }}
  .chip b {{ font-weight: 700; }}
  .chip.up b {{ color: var(--up); }}
  .chip.down b {{ color: var(--down); }}
  .chip.new {{ color: var(--new); border-color: #cfe0fb; }}
  .chip.out {{ color: #999; text-decoration: line-through; }}
  .chip a {{ color: inherit; text-decoration: none; }}
  .chip a:hover {{ text-decoration: underline; }}
  .movers-empty {{ font-size: 12px; color: var(--sub); margin-bottom: 14px; }}
  footer {{ text-align: center; color: var(--sub); font-size: 12px; margin-top: 24px; }}
  @media (max-width: 600px) {{
    td.rating, td.reviews, th.rating, th.reviews {{ display: none; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>📚 O'Reilly Learning Top Books</h1>
    <div class="sub">Collected: {today}</div>
  </header>
  <div class="tabs">{tabs_nav}</div>
  {tabs_panels}
  <footer>Unofficial, independent ranking based on O'Reilly's "popularity" score (the exact formula isn't published).<br>
  "Last N months" filters by <b>publication date</b>, not by actual reading activity — the O'Reilly API doesn't expose that.</footer>
</div>
<script>
  document.querySelectorAll('.tab-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
    }});
  }});
</script>
</body>
</html>
"""
    INDEX_HTML.write_text(html, encoding="utf-8")


def main():
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    today, pop_pool, recency_pool = load_pools(date_arg)

    view_data = {}
    for key, meta in VIEWS.items():
        books, total_candidates = build_view(pop_pool, recency_pool, meta["months"])
        prev_ranks, prev_titles, prev_date = load_prev_ranks(key, today)
        update_history(key, today, books)
        note = f"Previous run: {prev_date}" if prev_date else "Previous run: (first run)"
        if meta["months"] is not None:
            note += f" · Published within the last {meta['months']} month(s) ({total_candidates} candidates, showing top {len(books)})"
        movers = compute_movers(books, prev_ranks, prev_titles)
        view_data[key] = {
            "meta": {"label": meta["label"], "note": note},
            "rows": render_rows(books, prev_ranks),
            "movers_html": render_movers(movers, prev_date),
        }

    render_html(today, view_data)
    print(f"[OK] {today}: pop_pool={len(pop_pool)}, recency_pool={len(recency_pool)} -> rebuilt index.html with {len(VIEWS)} views.")


if __name__ == "__main__":
    main()
