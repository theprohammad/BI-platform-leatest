"""Competitor monitoring engine (Crayon-class) — real change detection.

A snapshot captures measurable signals from a competitor page (title, meta
description = messaging, detected pricing tokens, technology stack, headings,
word count). Diffing consecutive snapshots yields real, categorized change
events — never fabricated. Categories: messaging, pricing, tech, content,
feature. Each change carries a severity derived from what actually moved.

The signal extraction reuses the website analyzer, so the same crawl feeds SEO,
enrichment, and competitor monitoring. The diff logic here is pure and fully
unit-tested without network.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

# Price tokens: currency-prefixed or -suffixed numbers, and common plan words.
_PRICE_RE = re.compile(
    r"(?:[$€£]\s?\d[\d,]*(?:\.\d+)?(?:\s?/\s?(?:mo|month|yr|year|user))?)"
    r"|(?:\b\d[\d,]*\s?(?:USD|EUR|GBP)\b)",
    re.IGNORECASE,
)
_PLAN_RE = re.compile(r"\b(free|starter|basic|pro|professional|team|business|"
                      r"enterprise|premium|plus|ultimate)\b", re.IGNORECASE)


def extract_signals(analysis: dict) -> dict:
    """Reduce a full page analysis to the signals we monitor for change."""
    text_blob = " ".join([
        analysis.get("title", ""),
        analysis.get("meta_description", ""),
        " ".join(analysis.get("h1", []) or []),
    ])
    prices = sorted(set(m.group(0).strip() for m in _PRICE_RE.finditer(
        analysis.get("meta_description", "") + " " + " ".join(analysis.get("h1", []) or []))))
    plans = sorted(set(m.group(0).lower() for m in _PLAN_RE.finditer(text_blob)))
    return {
        "title": analysis.get("title", ""),
        "meta_description": analysis.get("meta_description", ""),
        "h1": analysis.get("h1", []) or [],
        "technologies": sorted(analysis.get("technologies", []) or []),
        "prices": prices,
        "plans": plans,
        "word_count": analysis.get("word_count", 0),
        "schema_types": sorted(analysis.get("schema_types", []) or []),
    }


def content_hash(signals: dict) -> str:
    key = "|".join([
        signals.get("title", ""),
        signals.get("meta_description", ""),
        ",".join(signals.get("h1", [])),
        ",".join(signals.get("technologies", [])),
        ",".join(signals.get("prices", [])),
        ",".join(signals.get("plans", [])),
    ])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass
class Change:
    category: str          # messaging|pricing|tech|content|feature
    severity: str          # critical|high|medium|low
    summary: str
    before: str = ""
    after: str = ""


def _list_delta(old: list[str], new: list[str]) -> tuple[list[str], list[str]]:
    olds, news = set(old), set(new)
    return sorted(news - olds), sorted(olds - news)


def diff_snapshots(old: dict, new: dict) -> list[Change]:
    """Compare two signal snapshots → real change events. Empty if nothing moved."""
    changes: list[Change] = []

    # --- messaging (title / meta description / H1) ---
    if old.get("title") and new.get("title") and old["title"] != new["title"]:
        changes.append(Change("messaging", "high",
                              "Homepage title changed.", old["title"], new["title"]))
    if (old.get("meta_description") and new.get("meta_description")
            and old["meta_description"] != new["meta_description"]):
        changes.append(Change("messaging", "medium",
                              "Meta description / positioning changed.",
                              old["meta_description"], new["meta_description"]))
    new_h1, gone_h1 = _list_delta(old.get("h1", []), new.get("h1", []))
    if new_h1 or gone_h1:
        changes.append(Change("messaging", "medium",
                              "Headline (H1) changed.",
                              "; ".join(old.get("h1", [])), "; ".join(new.get("h1", []))))

    # --- pricing ---
    added_p, removed_p = _list_delta(old.get("prices", []), new.get("prices", []))
    if added_p or removed_p:
        sev = "critical" if removed_p and not added_p else "high"
        parts = []
        if added_p:
            parts.append(f"added {', '.join(added_p)}")
        if removed_p:
            parts.append(f"removed {', '.join(removed_p)}")
        changes.append(Change("pricing", sev, f"Pricing changed: {'; '.join(parts)}.",
                              ", ".join(old.get("prices", [])), ", ".join(new.get("prices", []))))
    added_plan, removed_plan = _list_delta(old.get("plans", []), new.get("plans", []))
    if added_plan or removed_plan:
        # a removed 'free' tier or added 'enterprise' tier is high-signal
        sev = "high" if ("free" in removed_plan or "enterprise" in added_plan) else "medium"
        parts = []
        if added_plan:
            parts.append(f"new plan(s): {', '.join(added_plan)}")
        if removed_plan:
            parts.append(f"removed plan(s): {', '.join(removed_plan)}")
        changes.append(Change("pricing", sev, f"Plan lineup changed: {'; '.join(parts)}.",
                              ", ".join(old.get("plans", [])), ", ".join(new.get("plans", []))))

    # --- technology ---
    added_t, removed_t = _list_delta(old.get("technologies", []), new.get("technologies", []))
    if added_t or removed_t:
        parts = []
        if added_t:
            parts.append(f"adopted {', '.join(added_t)}")
        if removed_t:
            parts.append(f"dropped {', '.join(removed_t)}")
        changes.append(Change("tech", "medium", f"Technology stack changed: {'; '.join(parts)}.",
                              ", ".join(old.get("technologies", [])), ", ".join(new.get("technologies", []))))

    # --- content volume (a coarse "significant edit" signal) ---
    ow, nw = old.get("word_count", 0), new.get("word_count", 0)
    if ow and nw and abs(nw - ow) / max(ow, 1) >= 0.4:
        direction = "expanded" if nw > ow else "reduced"
        changes.append(Change("content", "low",
                              f"Homepage content {direction} substantially ({ow}→{nw} words).",
                              str(ow), str(nw)))

    return changes


@dataclass
class SnapshotResult:
    signals: dict
    content_hash: str
    changes: list[Change] = field(default_factory=list)
    is_first: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "signals": self.signals,
            "content_hash": self.content_hash,
            "is_first": self.is_first,
            "changes": [c.__dict__ for c in self.changes],
        }


def build_snapshot(analysis: dict, previous_signals: dict | None) -> SnapshotResult:
    """Turn a fresh analysis into a snapshot + the changes vs. the previous one."""
    signals = extract_signals(analysis)
    h = content_hash(signals)
    if previous_signals is None:
        return SnapshotResult(signals=signals, content_hash=h, is_first=True)
    changes = diff_snapshots(previous_signals, signals)
    return SnapshotResult(signals=signals, content_hash=h, changes=changes)
