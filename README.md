# O'Reilly Learning Top Books

An unofficial, independent tracker of popular books on O'Reilly Learning, based on the
platform's "popularity" score. Four views:

- **All time** — raw popularity order (long-tail: older evergreen titles tend to dominate)
- **Last 1 / 3 / 6 months** — restricted to books published in that window, then ranked
  by popularity within that window (recently published books rarely beat all-time
  favorites on raw popularity, so filtering first is what makes this useful)

Each run also highlights what changed since the previous run: 📈 gainers, 📉 losers,
🆕 new entries, and 📤 books that dropped out of the top 50.

**Live page:** see repo settings for the GitHub Pages URL, or open `index.html` directly.

## Why this isn't fully automated

O'Reilly uses Akamai Bot Manager. Hitting the API directly from a script (even with a
copied session cookie) gets blocked; only requests made from an actual logged-in browser
session go through. So data collection is a manual step done through
[Claude in Chrome](https://www.anthropic.com/claude-code) — no credentials are stored or
committed anywhere in this repo.

## Updating the data

This repo only ever contains derived, aggregated data (ranks + titles), never bulk
exports of O'Reilly's catalog. To refresh:

1. From a logged-in `learning.oreilly.com` session, fetch the top ~1200 books sorted by
   `popularity` and by `publication_date` (see `scripts/build_site.py` for the exact
   endpoints/fields).
2. Save the result as `data/pool/<date>.json` with shape `{pop_pool: [...], recency_pool: [...]}`.
3. Run:
   ```
   python3 scripts/build_site.py
   ```
   This rebuilds `index.html`, updates `data/history/*.json` (used to compute the
   day-over-day diff), and writes a Markdown blog post for the "Last month" view to
   `posts/<date>.md` (gitignored).
4. Commit and push (`index.html` and `data/history/*.json`) to update GitHub Pages.

## Publishing to Hatena Blog

The "Last month" post can be published to Hatena Blog via the AtomPub API:

```
python3 scripts/post_hatena.py [YYYY-MM-DD]            # publish (default: latest post)
python3 scripts/post_hatena.py --update [YYYY-MM-DD]   # overwrite an already published post
```

Credentials live in a local, gitignored `.env`:

```
HATENA_ID=<your Hatena ID>
HATENA_BLOG_ID=<yourblog>.hatenablog.com
HATENA_API_KEY=<AtomPub API key from the Hatena Blog settings>
```

A published post is recorded in `posts/<date>.url`, so re-running won't double-post.

## Directory layout

```
index.html                 Generated page (this is what gets published)
scripts/build_site.py       pool -> index.html + posts/<date>.md
scripts/post_hatena.py      posts/<date>.md -> Hatena Blog (AtomPub)
data/history/<view>.json    Per-view rank history (small, used for diffing)
data/pool/                  Raw fetched pools (gitignored — not published)
posts/                      Generated blog posts (gitignored)
.env                        Hatena credentials (gitignored)
```

## Notes

- "popularity" is O'Reilly's own metric; the exact formula isn't published. Looking at
  the raw values, it behaves like a monotonically-decreasing, near-fixed-step function of
  rank — more a rank-encoding than a literal usage count.
- "Last N months" filters by **publication date**, not by when people actually read the
  book — O'Reilly's API doesn't expose recency-of-reading data.
- This project only displays titles, authors, ranks, ratings, and links back to
  O'Reilly's own book pages — no cover images or content are reproduced.
