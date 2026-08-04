"""Application configuration.

Settings are read from environment variables (and an optional ``.env`` file)
via ``pydantic-settings``. Nothing here is required for the service to boot:
if ``ANTHROPIC_API_KEY`` is unset the ``/ask`` endpoint degrades gracefully to
returning the retrieved runbook chunks without LLM synthesis.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root, resolved relative to this file so the app runs from any cwd.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration for the RAG service.

    Attributes:
        anthropic_api_key: Anthropic API key. When empty, answer synthesis is
            skipped and the raw retrieved chunks are returned instead.
        claude_model: Model id used for answer synthesis.
        runbooks_dir: Directory containing the runbook markdown corpus.
        default_top_k: Number of chunks retrieved when the request omits ``top_k``.
        max_top_k: Upper bound on ``top_k`` accepted from a request.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-5"
    runbooks_dir: Path = _PROJECT_ROOT / "data" / "runbooks"
    default_top_k: int = 3
    max_top_k: int = 10

    @property
    def llm_enabled(self) -> bool:
        """True when an API key is present and LLM synthesis can run."""
        return bool(self.anthropic_api_key.strip())


def get_settings() -> Settings:
    """Return application settings (constructed fresh so tests can override env)."""
    return Settings()
