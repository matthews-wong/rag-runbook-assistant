"""Retrieval layer: ingest markdown runbooks, chunk them, and retrieve.

Retrieval uses a TF-IDF vector space with cosine similarity (scikit-learn), so
the service runs with zero external dependencies — no vector database, no
embedding API. The corpus is small enough that an in-memory index rebuilt at
startup is more than sufficient.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# A chunk boundary is a markdown heading (## ... or ###) or a blank-line gap.
_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)


@dataclass(frozen=True)
class Chunk:
    """A single retrievable unit of runbook text.

    Attributes:
        source: Filename the chunk came from (e.g. ``high-cpu-api-pods.md``).
        title: Nearest preceding heading, used as a human-readable citation.
        text: The chunk body, including its heading line.
    """

    source: str
    title: str
    text: str


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk paired with its similarity score for a given query."""

    chunk: Chunk
    score: float


@dataclass(frozen=True)
class RunbookInfo:
    """Summary of one indexed runbook document.

    Attributes:
        source: Filename of the runbook (e.g. ``redis-oom.md``).
        chunks: Number of indexed chunks the file contributed.
        sections: Section titles for those chunks, in document order.
    """

    source: str
    chunks: int
    sections: list[str]


def chunk_markdown(source: str, content: str) -> list[Chunk]:
    """Split one markdown document into heading-delimited chunks.

    Each chunk starts at a heading and runs until the next heading (or end of
    file). Text before the first heading is emitted as an untitled preamble
    chunk. Empty sections are dropped.

    Args:
        source: Filename used to attribute the resulting chunks.
        content: Raw markdown text.

    Returns:
        A list of :class:`Chunk` objects in document order.
    """
    matches = list(_HEADING_RE.finditer(content))
    chunks: list[Chunk] = []

    # Preamble: any text before the first heading.
    first_start = matches[0].start() if matches else len(content)
    preamble = content[:first_start].strip()
    if preamble:
        chunks.append(Chunk(source=source, title=source, text=preamble))

    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        section = content[start:end].strip()
        if not section:
            continue
        heading_line = section.splitlines()[0]
        title = heading_line.lstrip("#").strip() or source
        chunks.append(Chunk(source=source, title=title, text=section))

    return chunks


def load_chunks(runbooks_dir: Path) -> list[Chunk]:
    """Ingest every ``*.md`` file in ``runbooks_dir`` into chunks.

    Args:
        runbooks_dir: Directory to scan (non-recursively) for markdown files.

    Returns:
        Chunks from all files, sorted by source filename for determinism.

    Raises:
        FileNotFoundError: If ``runbooks_dir`` does not exist.
    """
    if not runbooks_dir.exists():
        raise FileNotFoundError(f"Runbooks directory not found: {runbooks_dir}")

    chunks: list[Chunk] = []
    for path in sorted(runbooks_dir.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        chunks.extend(chunk_markdown(path.name, content))
    return chunks


class RunbookIndex:
    """In-memory TF-IDF index over a runbook corpus.

    Build once at startup, then call :meth:`retrieve` per query. The vectorizer
    is fit on the chunk texts; queries are transformed into the same space and
    ranked by cosine similarity.
    """

    def __init__(self, chunks: list[Chunk]) -> None:
        """Build the TF-IDF matrix from ``chunks``.

        Args:
            chunks: Corpus to index. Must be non-empty.

        Raises:
            ValueError: If ``chunks`` is empty.
        """
        if not chunks:
            raise ValueError("Cannot build an index from an empty corpus.")
        self._chunks = chunks
        self._vectorizer = TfidfVectorizer(stop_words="english")
        self._matrix = self._vectorizer.fit_transform(c.text for c in chunks)

    @property
    def size(self) -> int:
        """Number of indexed chunks."""
        return len(self._chunks)

    def list_runbooks(self) -> list[RunbookInfo]:
        """Summarize indexed runbooks, grouped by source filename.

        Returns:
            One :class:`RunbookInfo` per source file, sorted by filename. Within
            each entry the section titles preserve document order.
        """
        grouped: dict[str, list[str]] = {}
        for chunk in self._chunks:
            grouped.setdefault(chunk.source, []).append(chunk.title)
        return [
            RunbookInfo(source=source, chunks=len(titles), sections=titles)
            for source, titles in sorted(grouped.items())
        ]

    def retrieve(
        self, query: str, top_k: int = 3, min_score: float = 0.0
    ) -> list[RetrievedChunk]:
        """Return the ``top_k`` chunks most similar to ``query``.

        Chunks with a similarity of zero (no shared vocabulary) are always
        excluded, so the result may be shorter than ``top_k`` — including empty
        when the query shares no terms with the corpus. A positive ``min_score``
        tightens this further, dropping weakly-matching chunks.

        Args:
            query: Natural-language question.
            top_k: Maximum number of chunks to return. Values below 1 yield [].
            min_score: Minimum cosine similarity a chunk must reach to be
                included. Defaults to 0.0 (only the zero-score exclusion applies).

        Returns:
            Retrieved chunks ordered by descending similarity score.
        """
        if top_k < 1 or not query.strip():
            return []

        query_vector = self._vectorizer.transform([query])
        scores = cosine_similarity(query_vector, self._matrix)[0]

        ranked = sorted(
            range(len(scores)), key=lambda i: scores[i], reverse=True
        )
        results: list[RetrievedChunk] = []
        for i in ranked[:top_k]:
            score = float(scores[i])
            # Scores are descending, so the first sub-threshold hit ends the run.
            if score <= 0.0 or score < min_score:
                break
            results.append(RetrievedChunk(chunk=self._chunks[i], score=score))
        return results


def build_index(runbooks_dir: Path) -> RunbookIndex:
    """Convenience: load chunks from disk and build an index in one call."""
    return RunbookIndex(load_chunks(runbooks_dir))
