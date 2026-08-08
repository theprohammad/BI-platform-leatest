"""Evidence chunker (spec S3): paragraph-boundary splits, target 1,200 chars,
150-char overlap, sequence-ordered. Deterministic — same content, same chunks
(reproducibility rule 2; the extraction cache key depends on it)."""

TARGET = 1200
OVERLAP = 150


def chunk_text(text: str, target: int = TARGET, overlap: int = OVERLAP) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= target:
        return [text]
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()] or [text]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        while len(para) > target:            # oversized paragraph: hard-wrap
            head, para = para[:target], para[max(0, target - overlap):]
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)
        if len(current) + len(para) + 2 <= target:
            current = f"{current}\n\n{para}" if current else para
        else:
            if current:
                chunks.append(current)
            current = (chunks[-1][-overlap:] + "\n\n" + para) if chunks and overlap else para
            if len(current) > target:        # overlap pushed it over
                chunks.append(current[:target])
                current = current[max(0, target - overlap):]
    if current:
        chunks.append(current)
    return chunks
