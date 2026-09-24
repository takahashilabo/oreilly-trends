#!/usr/bin/env python3
"""Publish posts/<date>.md to Hatena Blog via AtomPub.

Usage: python3 scripts/post_hatena.py [--update] [YYYY-MM-DD]   (default: latest post)
--update overwrites an already published post (same URL) with the current markdown.
Credentials are read from .env (gitignored): HATENA_ID, HATENA_BLOG_ID, HATENA_API_KEY.
"""
import base64
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
POSTS_DIR = ROOT / "posts"


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    missing = [k for k in ("HATENA_ID", "HATENA_BLOG_ID", "HATENA_API_KEY") if not env.get(k)]
    if missing:
        sys.exit(f"[ERROR] Missing in .env: {', '.join(missing)}")
    return env


def request(url, auth, method="GET", xml=None):
    req = urllib.request.Request(
        url, data=xml.encode("utf-8") if xml else None, method=method,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/atom+xml; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req) as res:
            return res.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        sys.exit(f"[ERROR] HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")


def find_edit_url(collection_url, auth, alternate):
    """Look up an entry's edit URL in the collection feed by its public URL."""
    feed = request(collection_url, auth)
    for entry in re.findall(r"<entry>.*?</entry>", feed, re.S):
        alt = re.search(r'<link rel="alternate"[^>]*href="([^"]+)"', entry)
        edit = re.search(r'<link rel="edit"[^>]*href="([^"]+)"', entry)
        if alt and edit and alt.group(1) == alternate:
            return edit.group(1)
    sys.exit("[ERROR] Entry not found in the latest feed page; cannot update.")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    update = "--update" in sys.argv
    if args:
        md = POSTS_DIR / f"{args[0]}.md"
    else:
        files = sorted(POSTS_DIR.glob("20*-*-*.md"))
        if not files:
            sys.exit("[ERROR] No posts/*.md. Run build_site.py first.")
        md = files[-1]
    if not md.exists():
        sys.exit(f"[ERROR] {md} not found.")
    done = md.with_suffix(".url")
    if done.exists() and not update:
        sys.exit(f"[SKIP] Already posted: {done.read_text().splitlines()[0]}")
    if update and not done.exists():
        sys.exit("[ERROR] --update needs an already published post (posts/<date>.url).")

    env = load_env()
    text = md.read_text(encoding="utf-8")
    m = re.match(r"# (.+)\n+", text)
    title, body = (m.group(1), text[m.end():]) if m else (md.stem, text)

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<entry xmlns="http://www.w3.org/2005/Atom" xmlns:app="http://www.w3.org/2007/app">
  <title>{escape(title)}</title>
  <author><name>{escape(env['HATENA_ID'])}</name></author>
  <content type="text/x-markdown">{escape(body)}</content>
  <app:control><app:draft>no</app:draft></app:control>
</entry>"""
    url = f"https://blog.hatena.ne.jp/{env['HATENA_ID']}/{env['HATENA_BLOG_ID']}/atom/entry"
    auth = base64.b64encode(f"{env['HATENA_ID']}:{env['HATENA_API_KEY']}".encode()).decode()
    if update:
        alternate = done.read_text().splitlines()[0]
        resp = request(find_edit_url(url, auth, alternate), auth, "PUT", xml)
    else:
        resp = request(url, auth, "POST", xml)
    m = re.search(r'<link rel="alternate"[^>]*href="([^"]+)"', resp)
    post_url = m.group(1) if m else "(URL not found in response)"
    done.write_text(post_url + "\n", encoding="utf-8")
    print(f"[OK] {'Updated' if update else 'Published'}: {post_url}")


if __name__ == "__main__":
    main()
