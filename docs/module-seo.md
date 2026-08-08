# SEO & Website Intelligence Module (Semrush-class)

Real, evidence-backed technical SEO auditing. Every value is **measured from the
live page** — nothing is fabricated. Data that genuinely requires a commercial
provider (keyword volume, backlinks, traffic) is explicitly marked *unavailable*
rather than invented (platform Rule 2).

## What it does

Given a URL, the module fetches the live page and produces:

- **Multi-dimensional health scores** (technical / on-page / content / security /
  overall) — each score derives from real detected issues, never an arbitrary
  number.
- **Categorized issues** with severity, a plain-language message, and a
  recommended fix (Semrush-style): missing/oversized title, meta description,
  H1 problems, canonical, viewport, lang, image alt-text, structured data,
  HTTPS, security headers, thin content.
- **On-page facts**: title/meta lengths, heading hierarchy, canonical, viewport,
  JSON-LD + schema.org types, Open Graph / Twitter cards, image alt coverage,
  internal/external/nofollow links, word count.
- **Technology stack** detected from real HTML/script signatures
  (React, Next.js, Vue, WordPress, Shopify, Stripe, GA, HubSpot, …).
- **Security**: HTTPS + presence of HSTS/CSP/X-Frame-Options/etc.
- **Social profiles** discovered from outbound links.
- **Audit history**: every audit is persisted as a timestamped snapshot,
  enabling trend tracking and page-over-time change detection.

## Backend

| Endpoint | Purpose |
|---|---|
| `POST /v2/tools/website-audit` | Run a real audit; persists a snapshot. Body: `{url, organization_id?}` |
| `GET /v2/website-audits` | Audit history (filter by `organization_id` / `url`) |
| `GET /v2/website-audits/{id}` | Full stored audit (all signals + issues) |

Core analyzer: `app/analyzers/website_intel.py`
- `analyze_html(url, html, …)` — pure, fully unit-tested analysis (no network).
- `audit_website(url)` — live fetch + analysis; returns `ok=False` honestly on
  failure.
- `health_scores(analysis)` — evidence-derived scores.

Persistence: `website_audits` table (migration `0004`), store helpers
`save_website_audit` / `list_website_audits` / `get_website_audit`.

## Frontend

Route: `src/routes/website-audit.tsx`
- URL bar → real audit → animated score gauges → categorized issues with fixes →
  on-page / technology / security / social panels → an explicit
  "requires a data provider" panel for backlink/keyword/traffic → recent-audit
  history grid.
- Premium loading skeletons, empty state, and an honest error state when a site
  can't be reached.

Service: `runWebsiteAudit` / `fetchAuditHistory` / `fetchAuditDetail` in
`src/services/intelligence.ts`.

## Honest limits

- **Live crawling requires outbound network** (available in deployment). In the
  sandbox the analysis logic is verified against fixtures; the fetch path runs
  for real wherever egress is open.
- **Keyword volume, backlinks, traffic** require a commercial data provider and
  are shown as unavailable — never fabricated.

## Tests

`tests/test_website_intel.py` — real SEO extraction, technology detection, issue
flagging, evidence-derived scoring (clean page provably beats broken), the full
persist → history → detail flow, and honest fetch-failure handling.
