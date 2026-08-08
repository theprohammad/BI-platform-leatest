# Sales Intelligence Module (Apollo-class)

A complete sales workflow built on **real collected data**: discover → enrich →
score → CRM → outreach → report. No contact emails are ever fabricated — public
contacts are surfaced with an explicit `found` / `not_found` status.

## Workflow

1. **Discover & enrich** — give a company name + domain. The shared website
   analyzer fetches real signals (tech stack, pricing/plans, messaging, schema,
   social profiles); if a GitHub profile is found, the GitHub connector adds real
   release activity. One crawl, reused across all three products.
2. **Lead scoring** (`app/analyzers/lead_scoring.py`) — an explainable 0–100
   score from five evidence-derived factors: **technology fit**, **buying
   signals**, **growth signals**, **ICP match**, **digital maturity**. Every
   factor carries the evidence behind its points; missing data lowers confidence
   rather than inventing a number. Bands: priority / hot / warm / cold.
3. **CRM** — leads persist with a 7-stage pipeline (discovered → qualified →
   contacted → meeting → proposal → won → lost), notes, tasks, and an append-only
   activity log.
4. **Outreach** — AI email generation via the real Groq-backed LLM router,
   grounded strictly in the lead's collected facts (and able to reference
   competitor changes from the Crayon module — unified graph). Plus a multi-step
   sequence scaffold.
5. **Reports** — pipeline distribution, conversion & contact rates, average lead
   quality.

## Backend

| Endpoint | Purpose |
|---|---|
| `POST /v2/sales/discover` | Enrich + score + persist a lead |
| `GET /v2/sales/leads` | Lead database with filters (stage, band, industry, min_score) |
| `GET /v2/sales/leads/{id}` | Full lead: enrichment, score breakdown, contacts, notes, tasks, activity |
| `POST /v2/sales/leads/{id}/stage` | Move pipeline stage (validated) |
| `POST /v2/sales/leads/{id}/notes` | Add note |
| `POST /v2/sales/leads/{id}/tasks` | Add task |
| `POST /v2/sales/tasks/{id}/complete` | Complete task |
| `POST /v2/sales/leads/{id}/email` | AI outreach email (grounded; honest if no LLM key) |
| `GET /v2/sales/leads/{id}/sequence` | Outreach sequence scaffold |
| `GET /v2/sales/pipeline` | Pipeline + conversion + lead-quality report |

Models: `leads`, `contacts`, `crm_notes`, `crm_tasks`, `crm_activities`
(migration `0006`). Enrichment/outreach logic: `app/analyzers/sales_intel.py`.

## Frontend

Route: `src/routes/lead-generation.tsx` (nav: Growth → Lead Generation)
- Discovery bar → pipeline stats ribbon → score-band filter → lead list.
- **Lead drawer** with three tabs: **Overview** (score breakdown bars with
  per-factor evidence, contacts with honest email status), **CRM** (stage
  buttons, notes, tasks, activity feed), **Outreach** (generate AI email +
  view grounded facts).

Service: `discoverLead` / `fetchLeads` / `fetchLeadDetail` / `moveLeadStage` /
`addLeadNote` / `addLeadTask` / `completeLeadTask` / `generateEmail` /
`fetchPipeline`.

## Honest limits

- **Verified emails / phone numbers** require a commercial contact provider.
  Public contacts are shown with `not_found` status; nothing is fabricated.
- **Revenue / funding / headcount** require enrichment providers; shown as
  unavailable until connected.
- Live crawling and live LLM calls require network + keys (deployment); logic is
  verified via fixtures and a scripted router in-sandbox.

## Tests

`tests/test_sales_intel.py` — evidence-derived scoring (strong=priority,
weak=cold+low-confidence, bounds), the full discover→CRM (stage/note/task)→
sequence→pipeline flow, honest contact email-status, and AI email generation via
the real router path.
