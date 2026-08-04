"""Unit tests for chunking and retrieval.

These tests exercise only the offline retrieval path — no network calls, no
Anthropic API usage. Synthesis is deliberately not tested here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import get_settings
from app.rag import RunbookIndex, build_index, chunk_markdown, load_chunks

_SAMPLE = """\
Intro preamble text before any heading.

# Title

Some intro under the title.

## First Section

Content about redis memory pressure and evictions.

## Second Section

Content about postgres connection pools and idle transactions.
"""


def test_chunk_markdown_splits_on_headings() -> None:
    chunks = chunk_markdown("sample.md", _SAMPLE)
    titles = [c.title for c in chunks]

    # Preamble + 3 headings (Title, First Section, Second Section).
    assert len(chunks) == 4
    assert titles[0] == "sample.md"  # untitled preamble uses the filename
    assert "First Section" in titles
    assert "Second Section" in titles


def test_chunk_markdown_no_headings_is_single_chunk() -> None:
    chunks = chunk_markdown("flat.md", "just some text\nwith no headings")
    assert len(chunks) == 1
    assert chunks[0].source == "flat.md"
    assert "no headings" in chunks[0].text


def test_chunk_markdown_empty_document() -> None:
    assert chunk_markdown("empty.md", "   \n  \n") == []


def test_chunk_text_includes_heading_line() -> None:
    chunks = chunk_markdown("sample.md", _SAMPLE)
    first_section = next(c for c in chunks if c.title == "First Section")
    assert first_section.text.startswith("## First Section")


def test_load_chunks_reads_corpus() -> None:
    settings = get_settings()
    chunks = load_chunks(settings.runbooks_dir)

    assert len(chunks) > 0
    sources = {c.source for c in chunks}
    # All five sample runbooks are ingested.
    assert "high-cpu-api-pods.md" in sources
    assert "postgres-connection-pool-exhausted.md" in sources
    assert "redis-oom.md" in sources
    assert "certificate-expiry.md" in sources
    assert "rolling-back-a-bad-deploy.md" in sources


def test_load_chunks_missing_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_chunks(tmp_path / "does-not-exist")


def test_index_retrieves_relevant_chunk() -> None:
    settings = get_settings()
    index = build_index(settings.runbooks_dir)

    results = index.retrieve("redis out of memory evictions", top_k=3)

    assert results, "expected at least one relevant chunk"
    top = results[0]
    assert top.chunk.source == "redis-oom.md"
    assert top.score > 0.0


def test_retrieval_ranks_postgres_question_to_postgres_runbook() -> None:
    settings = get_settings()
    index = build_index(settings.runbooks_dir)

    results = index.retrieve(
        "too many clients connection pool idle in transaction", top_k=1
    )

    assert len(results) == 1
    assert results[0].chunk.source == "postgres-connection-pool-exhausted.md"


def test_retrieval_scores_are_descending() -> None:
    settings = get_settings()
    index = build_index(settings.runbooks_dir)

    results = index.retrieve("certificate expired tls handshake", top_k=5)
    scores = [r.score for r in results]

    assert scores == sorted(scores, reverse=True)


def test_retrieval_respects_top_k() -> None:
    settings = get_settings()
    index = build_index(settings.runbooks_dir)

    results = index.retrieve("deploy rollback latency", top_k=2)
    assert len(results) <= 2


def test_retrieval_empty_query_returns_nothing() -> None:
    settings = get_settings()
    index = build_index(settings.runbooks_dir)

    assert index.retrieve("   ", top_k=3) == []
    assert index.retrieve("anything", top_k=0) == []


def test_retrieval_irrelevant_query_returns_no_zero_score_chunks() -> None:
    settings = get_settings()
    index = build_index(settings.runbooks_dir)

    # Vocabulary that shares no terms with the ops corpus.
    results = index.retrieve("zzzqqq nonexistent gibberish token", top_k=5)
    assert all(r.score > 0.0 for r in results)


def test_retrieval_min_score_drops_weak_matches() -> None:
    settings = get_settings()
    index = build_index(settings.runbooks_dir)

    query = "redis out of memory evictions"
    unfiltered = index.retrieve(query, top_k=5)
    assert len(unfiltered) >= 2, "need multiple hits to exercise the threshold"

    # A threshold just above the weakest hit must drop at least that chunk
    # while keeping the strongest.
    weakest = unfiltered[-1].score
    threshold = weakest + 1e-6
    filtered = index.retrieve(query, top_k=5, min_score=threshold)

    assert filtered, "the top match should survive the threshold"
    assert all(r.score >= threshold for r in filtered)
    assert len(filtered) < len(unfiltered)


def test_retrieval_min_score_above_all_returns_nothing() -> None:
    settings = get_settings()
    index = build_index(settings.runbooks_dir)

    # Cosine similarity is bounded by 1.0, so nothing can clear a min_score > 1.
    assert index.retrieve("redis oom", top_k=5, min_score=1.01) == []


def test_list_runbooks_covers_corpus() -> None:
    settings = get_settings()
    index = build_index(settings.runbooks_dir)

    infos = index.list_runbooks()
    sources = [i.source for i in infos]

    # Sorted by filename and one entry per source file.
    assert sources == sorted(sources)
    assert len(sources) == len(set(sources))
    assert "redis-oom.md" in sources

    for info in infos:
        assert info.chunks == len(info.sections)
        assert info.chunks >= 1
    # Chunk counts must reconcile with the flat corpus size.
    assert sum(i.chunks for i in infos) == index.size


def test_empty_corpus_index_raises() -> None:
    with pytest.raises(ValueError):
        RunbookIndex([])
