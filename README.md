# AI Radar — Living Document (Starter Kit)

A lightweight pipeline that updates a **living document** of AI/AR/VR/Robotics product news every day:
- Collects from official feeds (RSS-first).
- Classifies **status** (`Announced`, `Shipped`, `Upgraded`, `Preview`, `Deprecated`, `Delayed`).
- Appends to `products.csv` and emits a daily digest in `digests/`.

## Quick start (local)

```bash
pip install feedparser
python ai_radar.py
```

Outputs:
- `products.csv` — master living document (import into Google Sheets/Notion).
- `digests/daily_YYYY-MM-DD.md` — daily changelog you can email/post.

## GitHub Actions (daily at ~9am Denver)

Add this repo to GitHub and keep the included workflow:
```.github/workflows/ai_radar.yml```
It runs `ai_radar.py` daily at **15:00 UTC** (~09:00 America/Denver) and commits updates.

## Customize

- Add feeds in `ai_radar.py` (look for `FEEDS`). For non-RSS sites (e.g., Meta AI Blog, xAI News), either run **RSSHub** or add a small scraper step.
- Tune status detection in `STATUS_KEYWORDS`.
- Expand categories in `CATEGORY_GUESS`.
- Add per-company rules (e.g., Google I/O tags) for better product parsing.
- Pipe `products.csv` into Google Sheets/Notion via your preferred sync tool.

## Schema (products.csv)

| field | description |
|---|---|
| id | stable id (company+title+date hash) |
| company | e.g., OpenAI, Google, Meta |
| product | quick product handle extracted from title |
| category | Model/API, Tooling, Infra, Device/AR, Robotics |
| status | Announced, Shipped, Upgraded, Preview, Deprecated, Delayed |
| status_date | date tied to current status |
| first_seen / last_seen | when this entry was first/last observed |
| change_type | New, Launch, Update |
| version | version/major label if present |
| summary | short headline (from feed title) |
| source_title/source_url | provenance |
| source_type | RSS/Blog/Keynote/etc. |
| source_priority | official/community |
| confidence | rough 0–1 |
| tags/regions/notes | freeform |

## Pro tips

- **Google I/O tracking**: during I/O week, add the I/O-specific feed(s) and a rule that groups entries under a single "I/O 2025" tag and maps products (e.g., Gemini, Android XR, Vertex AI) to separate product rows.
- **AR/VR + Robotics**: add AWE, Meta Connect, Apple/visionOS, ROSCon, ICRA/IROS YouTube RSS channels for keynote-based updates (YouTube provides an RSS per channel).
- **Notion/Sheets**: Import `products.csv` once, then use a small sync (GitHub → Notion/Sheets) to keep it live.
- **Alerting**: Optionally send the digest to Slack/Discord/Email with a CLI step.

---

Made for fast iteration; refine the heuristics over time.
