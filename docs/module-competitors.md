# Competitor Monitoring Module (Crayon-class)

Continuous competitor monitoring with **real change detection**. The system
snapshots measurable signals from a competitor page and diffs consecutive
snapshots to produce genuine, categorized change events — never fabricated.

## How change detection works

1. **Scan** a competitor URL → the shared website analyzer fetches and measures
   the page (reused from the SEO module — one crawl, three products).
2. **Snapshot** the monitored signals: title, meta description (messaging),
   H1s, detected pricing tokens (`$49/mo`, `€79`, …), plan names (free / pro /
   enterprise / …), technology stack, word count, schema types.
3. **Diff** against the previous snapshot for that URL. Differences become
   `Change` events with a category and an evidence-derived severity:
   - **pricing** — price or plan lineup changed (removing a *free* tier or
     adding *enterprise* is high/critical).
   - **messaging** — title / meta / H1 changed.
   - **tech** — technology adopted or dropped.
   - **content** — homepage content expanded/reduced ≥40%.
4. The **first** scan of a URL sets a baseline (no changes). Every later scan
   detects real movement.

All diff logic is pure and fully unit-tested (no network).

## Backend

| Endpoint | Purpose |
|---|---|
| `POST /v2/competitors/monitor` | Scan a URL, snapshot, diff, persist changes. Body: `{organization_id, competitor_name, url, page_type?}` |
| `GET /v2/competitors/timeline` | Change timeline (newest first) |
| `GET /v2/competitors/alerts` | Unacknowledged changes, severity-ranked |
| `POST /v2/competitors/changes/{id}/acknowledge` | Dismiss an alert |
| `GET /v2/competitors/report` | Executive report: counts by category/severity, most-active competitors, recent timeline |
| `GET /v2/twins/{org}/competitors` | Evidence-backed competitor profiles (graph) |

Engine: `app/analyzers/competitor_monitor.py` (`extract_signals`,
`diff_snapshots`, `build_snapshot`). Persistence: `competitor_snapshots` +
`competitor_changes` tables (migration `0005`).

## Frontend

Route: `src/routes/monitoring.tsx` (nav: Research → Monitoring)
- Monitor bar (name + URL → **Scan now**) with baseline/changes feedback.
- **Change timeline** with before/after diffs, category icons, severity.
- **Alerts** rail (severity-ranked, dismissible).
- **Executive report** card (totals, by-category breakdown, most-active).

Service: `monitorCompetitor` / `fetchCompetitorTimeline` /
`fetchCompetitorAlerts` / `acknowledgeChange` / `fetchCompetitorReport`.

## Honest limits

- Live crawling requires outbound network (available in deployment); the diff
  engine is verified against fixtures in-sandbox.
- News / social / funding / hiring feeds require their own connectors (the
  connector framework is in place; GitHub release-tracking already exists).
  Until connected, those surfaces show nothing rather than fabricated events.

## Tests

`tests/test_competitor_monitor.py` — signal extraction, pricing/plan/tech/
content diffs, severity rules, identical-snapshot no-op, and the full
monitor→timeline→alerts→acknowledge→report flow, plus honest fetch-failure.
