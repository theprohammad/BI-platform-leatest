"""Search provider interface (rule 6). Results are normalized SearchResult
objects; full content is preserved (rule 4 — evidence is an asset, don't
truncate it at the door)."""
from dataclasses import dataclass
from typing import Protocol


@dataclass
class SearchResult:
    title: str
    url: str
    content: str
    score: float | None = None
    published_date: str | None = None

    def as_dict(self) -> dict:
        return {
            "title": self.title, "url": self.url, "snippet": self.content,
            "score": self.score, "published_date": self.published_date,
        }


class SearchProvider(Protocol):
    async def search(self, query: str, *, max_results: int) -> list[SearchResult]: ...
