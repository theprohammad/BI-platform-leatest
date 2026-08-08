from urllib.parse import urlparse

class KnowledgeCleaner:
    def clean(self, knowledge: dict):
        cleaned = {}
        for category, searches in knowledge.items():
            cleaned[category] = []
            seen_urls = set()
            for search in searches:
                cleaned_results = []
                for result in search.get("results", []):
                    title = result.get("title", "").strip()
                    url = result.get("url", "").strip()
                    snippet = result.get("snippet", "").strip()
                    # Ignore incomplete records
                    if not title or not url or not snippet:
                        continue
                    # Normalize URL
                    normalized_url = url.rstrip("/")
                    # Remove duplicates
                    if normalized_url in seen_urls:
                        continue
                    seen_urls.add(normalized_url)
                    cleaned_results.append({
                        "title": title,
                        "url": normalized_url,
                        "domain": urlparse(normalized_url).netloc,
                        "snippet": " ".join(snippet.split()),
                        "content": f"{title}\n{snippet}"
                    })
                cleaned[category].append({
                    "query": search.get("query", ""),
                    "results": cleaned_results
                })
        return cleaned