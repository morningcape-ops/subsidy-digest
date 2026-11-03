"""補助金ダイジェスト: Jグランツ公開APIから取得 -> Claudeで要約 -> 静的サイト生成。

環境変数:
  ANTHROPIC_API_KEY  未設定なら要約はAPIの文章を整形しただけのフォールバックになる
  SITE_URL           公開URL(sitemap用)。例: https://USER.github.io/subsidy-digest
  MAX_NEW            1回の実行で新規に要約する最大件数(既定30)
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "items.json"
SITE = ROOT / "site"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
API = "https://api.jgrants-portal.go.jp/exp/v1/public/subsidies"
KEYWORDS = ["補助金", "助成金", "支援金", "給付金"]
MAX_NEW = int(os.environ.get("MAX_NEW", "30"))
SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")
JST = timezone(timedelta(hours=9))
MODEL = "claude-haiku-5-5"


def get_json(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "subsidy-digest/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if i == retries - 1:
                raise
            print(f"retry {url[:80]}: {e}", file=sys.stderr)
            time.sleep(2 * (i + 1))


def fetch_list():
    found = {}
    for kw in KEYWORDS:
        q = urllib.parse.urlencode(
            {"keyword": kw, "sort": "created_date", "order": "DESC", "acceptance": 1}
        )
        for it in get_json(f"{API}?{q}").get("result", []):
            found[it["id"]] = it
    return found


def fetch_detail(sid):
    return get_json(f"{API}/id/{sid}")["result"][0]


def strip_html(s):
    s = re.sub(r"<(script|style).*?</\1>", "", s or "", flags=re.S)
    s = re.sub(r"<br\s*/?>|</p>|</li>|</tr>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def jst(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(JST)


def build_record(listing, d):
    return {
        "id": d["id"],
        "title": d.get("title") or listing.get("title"),
        "catch": strip_html(d.get("subsidy_catch_phrase")),
        "text": strip_html(d.get("detail"))[:4000],
        "purpose": d.get("use_purpose"),
        "industry": d.get("industry"),
        "area": d.get("target_area_search"),
        "employees": d.get("target_number_of_employees"),
        "rate": d.get("subsidy_rate"),
        "max": int(d["subsidy_max_limit"]) if d.get("subsidy_max_limit") else 0,
        "start": d.get("acceptance_start_datetime"),
        "end": d.get("acceptance_end_datetime"),
        "url": d.get("front_subsidy_detail_page_url"),
        "added": datetime.now(JST).strftime("%Y-%m-%d"),
    }


PROMPT = """以下は日本の補助金・助成金の公式情報です。事実だけを使って、読者(中小企業・個人事業主)向けの要約をJSONのみで出力してください。
ルール: 原文にない事項は書かない。推測しない。金額・日付は原文どおり。不明な項目は空文字にする。
出力形式: {{"summary":"100字以内の概要","who":"対象者","points":["要点1","要点2","要点3"]}}

タイトル: {title}
概要: {catch}
対象地域: {area} / 従業員数: {employees} / 業種: {industry}
補助率: {rate} / 上限額: {max}円
本文:
{text}
"""


def summarize(rec, client):
    if client is None:
        body = rec["catch"] or rec["text"][:200]
        return {"summary": body[:120], "who": "", "points": [], "ai": False}
    msg = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": PROMPT.format(**rec)}],
    )
    raw = "".join(b.text for b in msg.content if b.type == "text")
    m = re.search(r"\{.*\}", raw, re.S)
    out = json.loads(m.group(0))
    out["ai"] = True
    return out


def esc(s):
    return html.escape(str(s or ""))


def yen(n):
    return f"{n:,}円" if n else "公募要領を参照"


def page(title, desc, body, path_in_site):
    canonical = f'<link rel="canonical" href="{SITE_URL}/{path_in_site}">' if SITE_URL else ""
    ga = CONFIG.get("analytics_snippet", "")
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}">{canonical}
<link rel="stylesheet" href="{'../' if '/' in path_in_site else ''}style.css">{ga}</head>
<body><header><a href="{'../' if '/' in path_in_site else ''}index.html">{esc(CONFIG['site_name'])}</a></header>
<main>{body}</main>
<footer><p>{esc(CONFIG['disclaimer'])}</p></footer></body></html>"""


def card(rec):
    end = jst(rec["end"])
    left = (end - datetime.now(JST)).days if end else None
    badge = f'<span class="badge">あと{left}日</span>' if left is not None and left <= 14 else ""
    return (
        f'<li><a href="s/{rec["id"]}.html">{esc(rec["title"])}</a>{badge}'
        f'<div class="meta">{esc(rec["area"])} / 上限 {yen(rec["max"])} / 締切 '
        f'{end.strftime("%Y-%m-%d") if end else "-"}</div>'
        f'<p>{esc(rec["sum"]["summary"])}</p></li>'
    )


def detail_page(rec):
    s = rec["sum"]
    end, start = jst(rec["end"]), jst(rec["start"])
    points = "".join(f"<li>{esc(p)}</li>" for p in s.get("points", []))
    ad = CONFIG.get("ad_snippet", "")
    body = f"""<h1>{esc(rec['title'])}</h1>
<p class="lead">{esc(s['summary'])}</p>
<table>
<tr><th>対象地域</th><td>{esc(rec['area'])}</td></tr>
<tr><th>対象者</th><td>{esc(s.get('who'))}</td></tr>
<tr><th>従業員数</th><td>{esc(rec['employees'])}</td></tr>
<tr><th>補助率</th><td>{esc(rec['rate'])}</td></tr>
<tr><th>上限額</th><td>{yen(rec['max'])}</td></tr>
<tr><th>受付期間</th><td>{start.strftime('%Y-%m-%d') if start else '-'} 〜 {end.strftime('%Y-%m-%d') if end else '-'}</td></tr>
</table>
{'<h2>要点</h2><ul>' + points + '</ul>' if points else ''}
{ad}
<p><a class="btn" href="{esc(rec['url'])}" rel="noopener">公式情報(Jグランツ)で確認する</a></p>
<p class="note">{'この要約はAIが公式情報から作成しました。' if s.get('ai') else ''}申請前に必ず公式の公募要領をご確認ください。</p>"""
    return page(f"{rec['title']} | {CONFIG['site_name']}", s["summary"], body, f"s/{rec['id']}.html")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    items =json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {}
    listing = fetch_list()
    print(f"listed: {len(listing)} / cached: {len(items)}")

    client = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic

        client = anthropic.Anthropic()

    new_ids = [i for i in listing if i not in items][:MAX_NEW]
    for n, sid in enumerate(new_ids, 1):
        try:
            rec = build_record(listing[sid], fetch_detail(sid))
            rec["sum"] = summarize(rec, client)
            items[sid] = rec
            print(f"[{n}/{len(new_ids)}] {rec['title'][:40]}")
        except Exception as e:
            print(f"skip {sid}: {e}", file=sys.stderr)

    # 受付中のものだけ公開(listingに残っている=受付中)
    live = [items[i] for i in listing if i in items]
    live.sort(key=lambda r: r["added"], reverse=True)
    DATA.parent.mkdir(exist_ok=True)
    DATA.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    (SITE / "s").mkdir(parents=True, exist_ok=True)
    (SITE / "style.css").write_text((ROOT / "scripts" / "style.css").read_text(encoding="utf-8"), encoding="utf-8")

    for f in (ROOT / "public").glob("*"):
        (SITE / f.name).write_bytes(f.read_bytes())

    soon = sorted((r for r in live if r["end"]), key=lambda r: r["end"])[:10]
    today = datetime.now(JST).strftime("%Y-%m-%d")
    body = (
        f"<h1>{esc(CONFIG['site_name'])}</h1><p class='lead'>{esc(CONFIG['tagline'])}(更新: {today} / 受付中 {len(live)}件)</p>"
        "<h2>締切が近い</h2><ul class='list'>" + "".join(card(r) for r in soon) + "</ul>"
        "<h2>新着</h2><ul class='list'>" + "".join(card(r) for r in live[:50]) + "</ul>"
    )
    (SITE / "index.html").write_text(page(CONFIG["site_name"], CONFIG["tagline"], body, "index.html"), encoding="utf-8")
    for r in live:
        (SITE / "s" / f"{r['id']}.html").write_text(detail_page(r), encoding="utf-8")

    (SITE / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n" + (f"Sitemap: {SITE_URL}/sitemap.xml\n" if SITE_URL else ""), encoding="utf-8"
    )
    if SITE_URL:
        urls = [f"{SITE_URL}/"] + [f"{SITE_URL}/s/{r['id']}.html" for r in live]
        xml = "".join(f"<url><loc>{u}</loc><lastmod>{today}</lastmod></url>" for u in urls)
        (SITE / "sitemap.xml").write_text(
            f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{xml}</urlset>',
            encoding="utf-8",
        )
    print(f"built {len(live)} pages")


if __name__ == "__main__":
    main()
