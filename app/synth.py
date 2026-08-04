"""Answer synthesis via the Anthropic Claude API, with graceful fallback.

If an API key is configured, retrieved chunks are handed to Claude as grounding
context and the model writes a cited answer. If no key is set (or the SDK call
fails), the service degrades to returning a plain-text digest of the top
retrieved chunks so ``/ask`` never crashes and remains useful offline.
"""

from __future__ import annotations

from dataclasses import dataclass

import anthropic

from app.config import Settings
from app.rag import RetrievedChunk

_SYSTEM_PROMPT = (
    "You are an on-call operations assistant. Answer the engineer's question "
    "using ONLY the numbered runbook excerpts provided. Cite the excerpts you "
    "rely on inline using their bracketed number, e.g. [1]. If the excerpts do "
    "not contain enough information to answer, say so plainly rather than "
    "guessing. Be concise and action-oriented."
)

# Bound the synthesis response; runbook answers are short and actionable.
_MAX_TOKENS = 1024


@dataclass(frozen=True)
class Answer:
    """Result of an /ask call.

    Attributes:
        answer: The synthesized (or fallback) answer text.
        citations: Source titles of the chunks used as grounding, in order.
        synthesized: True if Claude produced the answer; False for the fallback.
    """

    answer: str
    citations: list[str]
    synthesized: bool


def _format_context(chunks: list[RetrievedChunk]) -> str:
    """Render retrieved chunks as a numbered, citable context block."""
    blocks = []
    for index, retrieved in enumerate(chunks, start=1):
        chunk = retrieved.chunk
        blocks.append(
            f"[{index}] Source: {chunk.source} — {chunk.title}\n{chunk.text}"
        )
    return "\n\n".join(blocks)


def _fallback_answer(question: str, chunks: list[RetrievedChunk]) -> Answer:
    """Build a no-LLM answer from the raw retrieved chunks."""
    if not chunks:
        return Answer(
            answer=(
                "No relevant runbook content was found for this question. "
                "Try rephrasing or adding a runbook that covers it."
            ),
            citations=[],
            synthesized=False,
        )

    lines = [
        "LLM synthesis is unavailable (no ANTHROPIC_API_KEY set). "
        "Returning the most relevant runbook excerpts:",
        "",
    ]
    for index, retrieved in enumerate(chunks, start=1):
        chunk = retrieved.chunk
        lines.append(f"[{index}] {chunk.source} — {chunk.title}")
        lines.append(chunk.text)
        lines.append("")
    return Answer(
        answer="\n".join(lines).strip(),
        citations=[r.chunk.title for r in chunks],
        synthesized=False,
    )


def synthesize_answer(
    question: str,
    chunks: list[RetrievedChunk],
    settings: Settings,
) -> Answer:
    """Produce an answer for ``question`` grounded in ``chunks``.

    Uses Claude when an API key is configured; otherwise (or on any SDK error)
    falls back to returning the retrieved excerpts directly.

    Args:
        question: The engineer's natural-language question.
        chunks: Chunks retrieved for the question, best first.
        settings: Application settings (API key, model id).

    Returns:
        An :class:`Answer`. ``synthesized`` indicates whether Claude was used.
    """
    if not settings.llm_enabled or not chunks:
        return _fallback_answer(question, chunks)

    context = _format_context(chunks)
    citations = [r.chunk.title for r in chunks]
    user_prompt = (
        f"Runbook excerpts:\n\n{context}\n\n"
        f"Question: {question}\n\n"
        "Answer the question using the excerpts above and cite them inline."
    )

    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=settings.claude_model,
            max_tokens=_MAX_TOKENS,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
    except Exception:  # noqa: BLE001 - degrade gracefully on any SDK/network error
        return _fallback_answer(question, chunks)

    if not text:
        return _fallback_answer(question, chunks)

    return Answer(answer=text, citations=citations, synthesized=True)
