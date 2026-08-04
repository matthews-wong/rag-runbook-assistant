"""FastAPI application exposing the RAG runbook assistant.

Endpoints:
    GET  /health    — liveness + index status.
    GET  /runbooks  — list the indexed runbooks and their sections.
    POST /ask       — answer an on-call question from the runbook corpus.

The TF-IDF index is built once at startup and reused across requests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.rag import RunbookIndex, build_index
from app.synth import synthesize_answer

# Cosine similarity is bounded to [0, 1] for non-negative TF-IDF vectors.
_MAX_SIMILARITY = 1.0

# Populated at startup; module-level so request handlers can reach them.
_settings: Settings = get_settings()
_index: RunbookIndex | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the runbook index once when the app boots."""
    global _index
    _index = build_index(_settings.runbooks_dir)
    yield


app = FastAPI(
    title="RAG Runbook Assistant",
    description=(
        "Answers on-call/operations questions from a corpus of runbook "
        "markdown files using TF-IDF retrieval and Claude for synthesis."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


class AskRequest(BaseModel):
    """Request body for POST /ask."""

    question: str = Field(..., min_length=1, description="The on-call question.")
    top_k: int | None = Field(
        default=None,
        ge=1,
        description="Number of runbook chunks to retrieve (defaults to config).",
    )
    min_score: float = Field(
        default=0.0,
        ge=0.0,
        le=_MAX_SIMILARITY,
        description=(
            "Discard retrieved chunks scoring below this cosine similarity "
            "threshold (0.0 keeps all non-zero matches)."
        ),
    )


class Citation(BaseModel):
    """A single cited source chunk."""

    source: str
    title: str
    score: float


class AskResponse(BaseModel):
    """Response body for POST /ask."""

    answer: str
    synthesized: bool
    citations: list[Citation]


class HealthResponse(BaseModel):
    """Response body for GET /health."""

    status: str
    llm_enabled: bool
    indexed_chunks: int


class RunbookSummary(BaseModel):
    """A single indexed runbook document in the /runbooks listing."""

    source: str
    chunks: int
    sections: list[str]


class RunbooksResponse(BaseModel):
    """Response body for GET /runbooks."""

    count: int
    runbooks: list[RunbookSummary]


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report liveness, whether LLM synthesis is enabled, and index size."""
    return HealthResponse(
        status="ok",
        llm_enabled=_settings.llm_enabled,
        indexed_chunks=_index.size if _index else 0,
    )


@app.get("/runbooks", response_model=RunbooksResponse)
def runbooks() -> RunbooksResponse:
    """List the indexed runbooks with their section titles and chunk counts."""
    assert _index is not None, "Index not initialized"  # set during lifespan

    summaries = [
        RunbookSummary(source=info.source, chunks=info.chunks, sections=info.sections)
        for info in _index.list_runbooks()
    ]
    return RunbooksResponse(count=len(summaries), runbooks=summaries)


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    """Retrieve relevant runbook chunks and synthesize a cited answer."""
    assert _index is not None, "Index not initialized"  # set during lifespan

    top_k = request.top_k or _settings.default_top_k
    top_k = min(top_k, _settings.max_top_k)

    retrieved = _index.retrieve(
        request.question, top_k=top_k, min_score=request.min_score
    )
    result = synthesize_answer(request.question, retrieved, _settings)

    citations = [
        Citation(source=r.chunk.source, title=r.chunk.title, score=round(r.score, 4))
        for r in retrieved
    ]
    return AskResponse(
        answer=result.answer,
        synthesized=result.synthesized,
        citations=citations,
    )
