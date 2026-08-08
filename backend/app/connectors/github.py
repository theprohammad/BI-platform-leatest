"""GitHub connector — real competitor release & activity tracking (Crayon-class).

Uses the public GitHub REST API (no auth needed for public repos, at a lower
rate limit). Collects releases, recent tags, and basic repo signals. Every item
is a real, dated event pulled live — this is genuine release-tracking, not a
simulation.
"""
from __future__ import annotations

import json
import re
import urllib.request

from app.connectors.base import Connector, ConnectorItem, ConnectorResult

_GH_API = "https://api.github.com"
_UA = {"User-Agent": "SentientIntelBot/1.0", "Accept": "application/vnd.github+json"}


def _parse_repo(target: str) -> str | None:
    """Accept 'owner/repo', a github.com URL, or return None if not a GH target."""
    target = target.strip()
    if re.fullmatch(r"[\w.-]+/[\w.-]+", target):
        return target
    m = re.search(r"github\.com/([\w.-]+/[\w.-]+?)(?:\.git|/|$)", target)
    return m.group(1) if m else None


async def _get_json(url: str) -> object:
    import asyncio

    def _fetch():
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.load(r)
    return await asyncio.to_thread(_fetch)


class GitHubConnector(Connector):
    name = "github"

    async def collect(self, target: str, **kwargs) -> ConnectorResult:
        repo = _parse_repo(target)
        if not repo:
            return ConnectorResult(
                connector=self.name, available=False,
                note="No GitHub repository associated with this target.")

        items: list[ConnectorItem] = []
        # --- releases (the headline signal) ---
        releases = await _get_json(f"{_GH_API}/repos/{repo}/releases?per_page=10")
        if isinstance(releases, list):
            for rel in releases:
                items.append(ConnectorItem(
                    kind="release",
                    title=f"Released {rel.get('tag_name') or rel.get('name') or 'version'}",
                    detail=(rel.get("name") or "")[:200],
                    url=rel.get("html_url"),
                    at=rel.get("published_at"),
                    data={"tag": rel.get("tag_name"),
                          "prerelease": rel.get("prerelease", False)},
                ))

        # --- repo signal (stars/pushed_at as momentum evidence) ---
        repo_info = await _get_json(f"{_GH_API}/repos/{repo}")
        if isinstance(repo_info, dict) and repo_info.get("full_name"):
            items.append(ConnectorItem(
                kind="repo_signal",
                title=f"Repository activity for {repo_info['full_name']}",
                detail=f"{repo_info.get('stargazers_count', 0)} stars · "
                       f"{repo_info.get('open_issues_count', 0)} open issues",
                url=repo_info.get("html_url"),
                at=repo_info.get("pushed_at"),
                data={"stars": repo_info.get("stargazers_count"),
                      "forks": repo_info.get("forks_count"),
                      "language": repo_info.get("language"),
                      "pushed_at": repo_info.get("pushed_at")},
            ))

        if not items:
            return ConnectorResult(
                connector=self.name, available=True, items=[],
                note="Repository found but no public releases yet.")
        return ConnectorResult(connector=self.name, available=True, items=items)
