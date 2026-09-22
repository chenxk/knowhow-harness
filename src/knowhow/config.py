"""Process settings. External credentials keep their conventional env names."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def project_root() -> Path:
    """Directory that contains this repo's pyproject.toml."""
    start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError("pyproject.toml not found from knowhow.config")


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else project_root() / path


class Settings(BaseSettings):
    """Runtime settings loaded from the environment and an optional `.env`."""

    model_config = SettingsConfigDict(
        env_prefix="KNOWHOW_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    mode: Literal["offline", "live"] = "offline"
    chat_model: str = "deepseek-chat"
    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENAI_API_KEY", "KNOWHOW_OPENAI_API_KEY"),
    )
    openai_base_url: str = Field(
        default="https://api.deepseek.com",
        validation_alias=AliasChoices("OPENAI_BASE_URL", "KNOWHOW_OPENAI_BASE_URL"),
    )
    mcp_enabled: bool = False
    mcp_config: Path = Path("config/mcp.yaml")
    corpus_dir: Path = Path("data/corpus")
    skills_dir: Path = Path("skills")
    golden_path: Path = Path("evals/golden.yaml")
    top_k: int = 4
    retrieve_threshold: float = 0.12
    langfuse_public_key: str = Field(
        default="",
        validation_alias=AliasChoices("LANGFUSE_PUBLIC_KEY", "KNOWHOW_LANGFUSE_PUBLIC_KEY"),
    )
    langfuse_secret_key: str = Field(
        default="",
        validation_alias=AliasChoices("LANGFUSE_SECRET_KEY", "KNOWHOW_LANGFUSE_SECRET_KEY"),
    )
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices("LANGFUSE_HOST", "KNOWHOW_LANGFUSE_HOST"),
    )

    @property
    def tracing_enabled(self) -> bool:
        return bool(self.langfuse_public_key.strip() and self.langfuse_secret_key.strip())

    @property
    def corpus_path(self) -> Path:
        return _resolve(self.corpus_dir)

    @property
    def skills_path(self) -> Path:
        return _resolve(self.skills_dir)

    @property
    def mcp_path(self) -> Path:
        return _resolve(self.mcp_config)

    @property
    def golden_file(self) -> Path:
        return _resolve(self.golden_path)

    def check(self) -> None:
        """Fail at startup when a selected mode points at missing config."""
        if self.mode == "live" and not self.openai_api_key.strip():
            raise RuntimeError("KNOWHOW_MODE=live requires OPENAI_API_KEY")
        if self.mcp_enabled and not self.mcp_path.is_file():
            raise RuntimeError(f"MCP config not found: {self.mcp_path}")
        if not self.corpus_path.is_dir():
            raise RuntimeError(f"corpus dir not found: {self.corpus_path}")
        if not self.skills_path.is_dir():
            raise RuntimeError(f"skills dir not found: {self.skills_path}")
        if not self.golden_file.is_file():
            raise RuntimeError(f"golden file not found: {self.golden_file}")

    def export_langfuse_env(self) -> None:
        """Langfuse's client reads these names from the process environment."""
        if not self.tracing_enabled:
            return
        os.environ["LANGFUSE_PUBLIC_KEY"] = self.langfuse_public_key
        os.environ["LANGFUSE_SECRET_KEY"] = self.langfuse_secret_key
        os.environ["LANGFUSE_HOST"] = self.langfuse_host
