"""Connector layer — free-provider intelligence collection. Tests verify the
normalization logic and honest-failure behavior deterministically (mocking the
network transport), plus the concurrent fan-out. No fabricated data ever."""
import asyncio

import pytest

from app.connectors.base import Connector, ConnectorItem, ConnectorResult, collect_all
from app.connectors import github as gh


def test_github_repo_parsing():
    assert gh._parse_repo("tiangolo/fastapi") == "tiangolo/fastapi"
    assert gh._parse_repo("https://github.com/vercel/next.js") == "vercel/next.js"
    assert gh._parse_repo("https://github.com/a/b.git") == "a/b"
    assert gh._parse_repo("acme.com") is None
    assert gh._parse_repo("just-a-word") is None


async def test_github_connector_normalizes_real_shape(monkeypatch):
    """Given a GitHub-shaped API response, connector produces normalized items."""
    releases = [
        {"tag_name": "v1.2.0", "name": "Big launch", "html_url": "https://gh/r1",
         "published_at": "2026-07-16T15:05:47Z", "prerelease": False},
        {"tag_name": "v1.1.0", "name": "", "html_url": "https://gh/r2",
         "published_at": "2026-07-01T10:00:00Z", "prerelease": True},
    ]
    repo_info = {"full_name": "acme/app", "stargazers_count": 1200,
                 "open_issues_count": 8, "html_url": "https://gh/acme/app",
                 "pushed_at": "2026-07-17T00:00:00Z", "forks_count": 90,
                 "language": "Python"}

    async def fake_get_json(url):
        return releases if "releases" in url else repo_info
    monkeypatch.setattr(gh, "_get_json", fake_get_json)

    res = await gh.GitHubConnector().collect("acme/app")
    assert res.available is True
    kinds = [i.kind for i in res.items]
    assert kinds.count("release") == 2
    assert "repo_signal" in kinds
    rel = res.items[0]
    assert rel.title == "Released v1.2.0"
    assert rel.at == "2026-07-16T15:05:47Z"
    assert rel.url == "https://gh/r1"


async def test_github_connector_non_github_target_is_honest():
    res = await gh.GitHubConnector().collect("acme.com")
    assert res.available is False
    assert "No GitHub repository" in res.note
    assert res.items == []


async def test_connector_failure_never_fabricates(monkeypatch):
    """A transport error yields available=False + note, never fake items."""
    async def boom(url):
        raise RuntimeError("403 Forbidden")
    monkeypatch.setattr(gh, "_get_json", boom)
    # collect_cached is the wrapper the pipeline uses; it must swallow + report
    from app.core import throttle
    throttle.search_cache._data.clear()
    res = await gh.GitHubConnector().collect_cached("acme/app")
    assert res.available is False
    assert res.items == []
    assert "unavailable" in res.note.lower()


async def test_collect_all_fans_out_and_isolates_failures():
    class Good(Connector):
        name = "good"
        async def collect(self, target, **k):
            return ConnectorResult(connector="good", available=True,
                                   items=[ConnectorItem(kind="x", title="ok")])

    class Bad(Connector):
        name = "bad"
        async def collect(self, target, **k):
            raise RuntimeError("down")

    from app.core import throttle
    throttle.search_cache._data.clear()
    out = await collect_all([Good(), Bad()], "target")
    assert out["good"].available is True and out["good"].items
    assert out["bad"].available is False   # isolated, not fatal
