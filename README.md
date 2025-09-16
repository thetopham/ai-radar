# AI Radar — Daily Product Tracker

AI Radar keeps a living dataset of AI/ML/Robotics launch news up to date. The
pipeline fetches RSS feeds, classifies the maturity of each announcement, and
produces both a canonical CSV and a daily digest you can share with your team.

## Pipeline at a glance
- Loads feed definitions from `ai_radar_sources.opml`; automatically falls back
  to the built-in `DEFAULT_FEEDS` list inside `ai_radar.py` if the OPML file is
  missing.
- Parses each source with `feedparser`, tags the company/product, and assigns a
  status (`Announced`, `Preview`, `Upgraded`, `Shipped`, `Deprecated`, `Delayed`).
- Deduplicates entries by source URL, tracks promotions when a status improves,
  and keeps `products.csv` sorted for easy imports into Sheets/Notion.
- Enriches entries with vertical tags derived from the OPML hierarchy so
  robotics/XR-focused sources are easy to segment.
- Emits markdown digests in `digests/daily_YYYY-MM-DD.md` containing every new
  or promoted item with cleaned, digest-sized summaries.

## Local setup
1. (Optional) Create a virtualenv: `python -m venv .venv && source .venv/bin/activate`
2. Install the runtime dependency: `pip install feedparser`
3. Run the pipeline: `python ai_radar.py`

Outputs after a successful run:
- `products.csv` — the authoritative dataset; append-only except for status
  promotions.
- `digests/daily_YYYY-MM-DD.md` — rendered digest for the current day. Each run
  writes a new file, so prior digests remain untouched.

## Configuration knobs
Environment variables let you tune behaviour without editing code:
- `AI_RADAR_OPML` — path to an OPML file with feeds (defaults to
  `ai_radar_sources.opml` in the repo).
- `AI_RADAR_DIGEST_DAYS` — integer window (days) for digest inclusion.
- `AI_RADAR_DIGEST_LIMIT` — maximum number of items to include in a digest.
- `AI_RADAR_SKIP_FIRST_DIGEST` — set to `1`/`true` to suppress the initial digest
  when seeding historical data.

The heuristics that back these controls live in `ai_radar.py`:
- `STATUS_KEYWORDS` — regexes that map text snippets to the status labels.
- `CATEGORY_GUESS` — lightweight product categorisation rules.
- `parse_company` — maps feed names and hostnames to a canonical company label.
- `iter_feed` and `upsert` — core helpers that ingest entries and manage
  deduplication/status promotions.

Update `ai_radar_sources.opml` alongside code changes so new feeds are tracked in
version control. When you add dependencies beyond `feedparser`, pin them in
`requirements.txt` and document new CLI flags inside the module docstring.

## Data schema (`products.csv`)

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
| confidence | rough 0–1 score |
| tags/regions/notes | freeform fields for verticals or GTM notes |

## Automate with GitHub Actions
A ready-to-use workflow lives at `.github/workflows/ai_radar.yml`. It mirrors the
local command (`python ai_radar.py`) and runs every day at **15:00 UTC**.

To automate your instance:
1. Push this repository (or your fork) to GitHub with the workflow file intact.
2. Review the schedule in the workflow and adjust if you prefer another time.
   Test locally first so the CLI behaviour and GitHub Actions output stay in
   sync before committing changes to the schedule.
3. If any feeds require credentials, add them as repository secrets (for
   example `AI_RADAR_FEED_TOKEN`) and reference them via `env:` in the workflow.
4. Trigger a manual "Run workflow" once to confirm it writes to `products.csv`
   and creates the day’s digest under `digests/`.
5. Let the scheduled runs handle daily updates; each run commits the refreshed
   CSV and digest back to the repository history.

## Customisation tips
- Expand `DEFAULT_FEEDS` or your OPML file with additional vendor blogs,
  research labs, or robotics news sources. Keep feed additions paired with a
  change to `ai_radar_sources.opml` for traceability.
- Refine headline parsing or tagging by editing `parse_company` and the regex
  patterns in `STATUS_KEYWORDS` / `CATEGORY_GUESS`.
- For richer reporting, ship the generated digest to Slack/Discord/Email using a
  small wrapper script or an extra step in the GitHub Actions workflow.

Made for fast iteration—refine the heuristics over time and share learnings back! 
