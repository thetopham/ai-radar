# Repository Guidelines

## Recent Pipeline Improvements (v1.3)
- Daily digests now merge both net-new items and any status promotions surfaced by `upsert`, so keep promotion heuristics intact when refactoring.
- Feed ingestion assigns vertical tags (`ai`, `robotics`, `xr`, `research`) from `ai_radar_sources.opml`; updates to the OPML should preserve those labels so digest tagging stays accurate.
- Item summaries are normalised via `normalize_summary`, producing clean ≤500 character blurbs for digests—preserve this helper when adjusting feed parsing.
- Daily digests respect `AI_RADAR_DIGEST_DAYS`, `AI_RADAR_DIGEST_LIMIT`, and `AI_RADAR_SKIP_FIRST_DIGEST`; document new environment knobs in module docstrings when adding more controls.

## Project Structure & Module Organization
- `ai_radar.py` runs the daily pipeline: ingest RSS feeds, classify status, and update outputs.
- `products.csv` is the canonical dataset; treat schema changes as breaking and coordinate before modifying.
- `digests/` stores rendered daily summaries (`daily_YYYY-MM-DD.md`). New runs should append rather than overwrite.
- `.github/workflows/ai_radar.yml` schedules the automation at 15:00 UTC; keep it aligned with local CLI behaviour before pushing.
- `ai_radar_sources.opml` lists seed feeds; update alongside code when adding/removing sources for traceability.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate` creates an isolated environment.
- `pip install feedparser` pulls the lone runtime dependency; pin versions in `requirements.txt` if you add more.
- `python ai_radar.py` runs the full pipeline, updating `products.csv` and emitting a new digest. Use `PYTHONPATH=.` if you split modules later.
- `python ai_radar.py --since 2024-01-01` (example extension) is preferred for scoped replays; document new flags inside the module docstring.

## Coding Style & Naming Conventions
- Target Python 3.10+ and follow PEP 8 with 4-space indentation. Maintain clear separation between fetch, parse, and persist helpers.
- Use `snake_case` for functions and module globals (`FEEDS`, `STATUS_KEYWORDS`). Reserve `CamelCase` for dataclasses or future models.
- Document heuristics inline with concise comments; prefer pure functions over side-effect-heavy blocks for easier testing.

## Testing Guidelines
- Add unit tests under `tests/` using `pytest`. Mirror feed classification cases and CSV formatting edge cases.
- Run `pytest` before pushing; include regression fixtures (`fixtures/sample_feed.xml`) when reproducing issues.
- After code changes, execute `python ai_radar.py` and confirm the latest digest and CSV rows look sane (`git diff products.csv`).

## Commit & Pull Request Guidelines
- Follow the existing `type: summary` pattern (e.g., `chore: daily radar update`, `feat: add robotics feed`). Keep the first line under 72 characters.
- Reference related issues in the body, list manual verification steps, and attach digest or CSV excerpts when relevant.
- PRs should state data-impacting changes, migration steps, and backfill instructions if historical reprocessing is required.

## Security & Configuration Tips
- Store private feed URLs or API tokens in environment variables (`export AI_RADAR_FEED_TOKEN=...`) and read them via `os.getenv`.
- Validate new feeds with a dry run before enabling in GitHub Actions to avoid noisy commits or rate limits.
- Keep dependencies minimal; audit any new packages for licenses compatible with your deployment.
