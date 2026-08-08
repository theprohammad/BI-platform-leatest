"""Server-side exports: executive PDF reports and structured CSV datasets.

Design notes
------------
* **One reporting vocabulary.** Report kinds mirror the existing client-side
  report system (executive / board / research / opportunity) rather than
  inventing a parallel taxonomy.
* **Never fabricate.** Only values actually present in the intelligence are
  rendered. Sections with no data print an explicit "not collected" line
  instead of a plausible-looking placeholder, and no chart is drawn unless real
  numeric data backs it.
* **No internal terminology.** Reports are executive documents: no graph, agent,
  reviewer or pipeline wording, and no internal identifiers unless a reader
  genuinely needs them.
* **Caller enforces tenancy.** These builders receive already-scoped data; the
  API layer is responsible for verifying workspace/organization ownership.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

REPORT_KINDS = {
    "executive": ("Executive Summary", "Leadership"),
    "board": ("Board Report", "Board & investors"),
    "research": ("Research Report", "Strategy & analysts"),
    "opportunity": ("Opportunity Report", "Operators"),
}

# Datasets available for CSV export, mapped to their column order.
CSV_DATASETS = {
    "findings": ["organization", "finding", "topic", "confidence",
                 "source_count", "status", "as_of", "created_at"],
    "recommendations": ["organization", "recommendation", "confidence",
                        "supporting_findings", "status"],
    "competitor_changes": ["organization", "competitor", "category", "severity",
                           "summary", "before", "after", "acknowledged",
                           "detected_at"],
    "leads": ["organization", "company", "domain", "industry", "stage",
              "score", "score_band", "created_at"],
    "website_audits": ["organization", "url", "ok", "overall_score",
                       "created_at"],
}

_ACCENT = colors.HexColor("#6d28d9")
_MUTED = colors.HexColor("#6b7280")
_HAIRLINE = colors.HexColor("#e5e7eb")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=22,
                                spaceAfter=4, textColor=colors.HexColor("#111827")),
        "subtitle": ParagraphStyle("st", parent=base["Normal"], fontSize=10,
                                   textColor=_MUTED, spaceAfter=18),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=13,
                             spaceBefore=16, spaceAfter=6,
                             textColor=colors.HexColor("#111827")),
        "body": ParagraphStyle("b", parent=base["Normal"], fontSize=9.8,
                               leading=14.5, alignment=TA_LEFT),
        "muted": ParagraphStyle("m", parent=base["Normal"], fontSize=8.8,
                                textColor=_MUTED, leading=12.5),
    }


def _pct(v) -> str:
    try:
        return f"{round(float(v) * 100)}%"
    except (TypeError, ValueError):
        return "—"


def _esc(text: str) -> str:
    """Escape for ReportLab's mini-markup so stray angle brackets can't break
    rendering (report text comes from collected web content)."""
    return (str(text or "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _not_collected(styles, what: str):
    return Paragraph(
        f"<i>{_esc(what)} has not been collected for this organization.</i>",
        styles["muted"])


def build_report_pdf(kind: str, org_name: str, data: dict) -> bytes:
    """Render an executive PDF. `data` is the already-scoped intelligence:
    counts, recommendations, verified findings, conflicts, competitor changes
    and sources. Returns raw PDF bytes."""
    title, audience = REPORT_KINDS.get(kind, REPORT_KINDS["executive"])
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"{org_name} — {title}", author="Sentient Intelligence OS")

    story = []
    generated = datetime.now(timezone.utc).strftime("%d %B %Y")

    # ---- Cover / header ----
    story.append(Paragraph(_esc(org_name), styles["title"]))
    story.append(Paragraph(
        f"{_esc(title)} &nbsp;·&nbsp; Prepared for {_esc(audience)} "
        f"&nbsp;·&nbsp; {generated}", styles["subtitle"]))

    counts = data.get("counts") or {}
    summary_rows = [
        ["Verified findings", str(counts.get("validated", 0))],
        ["Recommendations", str(counts.get("recommendations", 0))],
        ["Conflicting intelligence", str(counts.get("disputes_open", 0))],
        ["Investigations run", str(counts.get("runs", 0))],
    ]
    tbl = Table(summary_rows, colWidths=[70 * mm, 25 * mm], hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (0, -1), _MUTED),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, _HAIRLINE),
    ]))
    story.append(Paragraph("At a glance", styles["h2"]))
    story.append(tbl)

    # ---- Executive summary ----
    story.append(Paragraph("Executive summary", styles["h2"]))
    verified = counts.get("validated", 0)
    actions = counts.get("recommendations", 0)
    conflicts = counts.get("disputes_open", 0)
    if verified == 0 and actions == 0:
        story.append(_not_collected(styles, "Intelligence"))
    else:
        story.append(Paragraph(
            f"We have verified {verified} finding{'' if verified == 1 else 's'} "
            f"about {_esc(org_name)} and identified {actions} recommended "
            f"action{'' if actions == 1 else 's'}. "
            + (f"{conflicts} item{'' if conflicts == 1 else 's'} require review "
               "because sources disagree."
               if conflicts else "No sources currently disagree."),
            styles["body"]))

    recs = data.get("recommendations") or []
    findings = data.get("findings") or []
    changes = data.get("competitor_changes") or []
    conflicts_list = data.get("conflicts") or []
    sources = data.get("sources") or []

    # ---- Recommendations ----
    if kind in ("executive", "board", "opportunity", "research"):
        story.append(Paragraph(
            "Opportunities" if kind == "opportunity" else "Recommendations",
            styles["h2"]))
        if not recs:
            story.append(_not_collected(styles, "Recommendations"))
        else:
            limit = 3 if kind == "board" else 10
            for r in recs[:limit]:
                story.append(Paragraph(
                    f"<b>{_esc(r.get('title'))}</b> &nbsp;"
                    f"<font color='#6b7280'>{_pct(r.get('confidence'))} confidence</font>",
                    styles["body"]))
                body = r.get("body")
                if body and kind != "board":
                    story.append(Paragraph(_esc(body), styles["muted"]))
                story.append(Spacer(1, 6))

    # ---- Verified findings ----
    story.append(Paragraph("Verified findings", styles["h2"]))
    if not findings:
        story.append(_not_collected(styles, "Verified findings"))
    else:
        limit = 4 if kind == "board" else (40 if kind == "research" else 12)
        for f in findings[:limit]:
            story.append(Paragraph(
                f"{_esc(f.get('title'))} &nbsp;"
                f"<font color='#6b7280'>({_pct(f.get('confidence'))})</font>",
                styles["body"]))
            story.append(Spacer(1, 3))

    # ---- Conflicts ----
    if conflicts_list:
        story.append(Paragraph("Conflicting intelligence", styles["h2"]))
        for c in conflicts_list[:8]:
            story.append(Paragraph(_esc(c.get("title")), styles["body"]))
            story.append(Paragraph(
                "Sources disagree — review before relying on this.",
                styles["muted"]))
            story.append(Spacer(1, 4))

    # ---- Competitive changes ----
    if changes:
        story.append(Paragraph("Competitive changes", styles["h2"]))
        rows = [["Competitor", "Category", "Severity", "Detected"]]
        for c in changes[:12]:
            rows.append([
                _esc(c.get("competitor_name"))[:28],
                _esc(c.get("category")),
                _esc(c.get("severity")),
                str(c.get("detected_at", ""))[:10],
            ])
        t = Table(rows, colWidths=[55 * mm, 35 * mm, 30 * mm, 30 * mm],
                  hAlign="LEFT")
        t.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8.6),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, 0), (-1, 0), _ACCENT),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#f9fafb")]),
            ("GRID", (0, 0), (-1, -1), 0.3, _HAIRLINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t)

    # ---- Sources appendix (research report only: it is long) ----
    if kind == "research" and sources:
        story.append(PageBreak())
        story.append(Paragraph("Supporting sources", styles["h2"]))
        for s in sources[:60]:
            story.append(Paragraph(_esc(s.get("domain") or s.get("url")),
                                   styles["body"]))
            if s.get("url"):
                story.append(Paragraph(_esc(s["url"]), styles["muted"]))
            story.append(Spacer(1, 3))

    story.append(Spacer(1, 18))
    story.append(Paragraph(
        "Generated by Sentient Intelligence OS. Every statement is backed by "
        "collected sources; figures requiring a commercial data provider are "
        "omitted rather than estimated.", styles["muted"]))

    doc.build(story)
    return buf.getvalue()


def build_csv(dataset: str, rows: list[dict]) -> str:
    """Render a structured CSV. Columns are fixed per dataset so consumers get
    real tabular data rather than a serialized blob."""
    columns = CSV_DATASETS.get(dataset)
    if columns is None:
        raise ValueError(f"unknown dataset '{dataset}'")
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore",
                            lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in columns})
    return out.getvalue()
