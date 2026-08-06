"""HTTP-level tests for the FastAPI endpoints.

These tests exercise the API surface through Starlette's ``TestClient`` and make
no network calls: the Anthropic API is never contacted. ``/ask`` cases are kept
in the fallback path (empty retrieval or LLM disabled) so no key is required and
no request leaves the process.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient whose context manager runs the index-building lifespan.

    LLM synthesis is force-disabled so the tests never contact the Anthropic
    API even if an ``ANTHROPIC_API_KEY`` is present in the environment.
    """
    import app.main as main

    monkeypatch.setattr(main._settings, "anthropic_api_key", "")
    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_index_size(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["indexed_chunks"] > 0
    assert isinstance(body["llm_enabled"], bool)


def test_runbooks_lists_corpus(client: TestClient) -> None:
    response = client.get("/runbooks")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == len(body["runbooks"])
    assert body["count"] > 0

    sources = [rb["source"] for rb in body["runbooks"]]
    assert "redis-oom.md" in sources
    assert sources == sorted(sources)

    for runbook in body["runbooks"]:
        assert runbook["chunks"] == len(runbook["sections"])
        assert runbook["chunks"] >= 1


def test_ask_rejects_blank_question(client: TestClient) -> None:
    response = client.post("/ask", json={"question": ""})
    assert response.status_code == 422


def test_ask_rejects_out_of_range_min_score(client: TestClient) -> None:
    response = client.post(
        "/ask", json={"question": "redis oom", "min_score": 2.0}
    )
    assert response.status_code == 422


def test_ask_no_match_returns_fallback_without_network(client: TestClient) -> None:
    # A min_score of 1.0 excludes every real match, so retrieval is empty and
    # synthesis short-circuits to the fallback — guaranteeing no API call.
    response = client.post(
        "/ask",
        json={"question": "redis is out of memory", "min_score": 1.0},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["synthesized"] is False
    assert body["citations"] == []
    assert "No relevant runbook content" in body["answer"]


def test_search_returns_ranked_chunks_without_synthesis(client: TestClient) -> None:
    response = client.get(
        "/search", params={"q": "redis out of memory evictions", "top_k": 3}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "redis out of memory evictions"
    assert body["count"] == len(body["results"])
    assert 1 <= body["count"] <= 3

    hits = body["results"]
    top = hits[0]
    assert top["source"] == "redis-oom.md"
    assert top["score"] > 0.0
    assert top["text"].strip()  # the chunk body is returned for inspection
    # Scores are ranked best-first.
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_search_rejects_blank_query(client: TestClient) -> None:
    assert client.get("/search", params={"q": ""}).status_code == 422


def test_search_rejects_out_of_range_min_score(client: TestClient) -> None:
    response = client.get(
        "/search", params={"q": "redis oom", "min_score": 2.0}
    )
    assert response.status_code == 422


def test_search_min_score_can_exclude_all_matches(client: TestClient) -> None:
    # Cosine similarity is bounded by 1.0, so a threshold of 1.0 drops every hit.
    response = client.get(
        "/search", params={"q": "redis is out of memory", "min_score": 1.0}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert body["results"] == []


def test_ask_returns_scored_citations(client: TestClient) -> None:
    response = client.post(
        "/ask", json={"question": "redis out of memory evictions", "top_k": 2}
    )

    assert response.status_code == 200
    body = response.json()
    assert 1 <= len(body["citations"]) <= 2

    citation = body["citations"][0]
    assert citation["source"].endswith(".md")
    assert citation["score"] > 0.0
