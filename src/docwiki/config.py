from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCWIKI_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    generation_model: Literal["gpt-4o-mini"] = "gpt-4o-mini"
    embedding_model: Literal["text-embedding-3-small"] = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    document_bytes: int = Field(10 * 1024 * 1024, gt=0)
    questions_bytes: int = Field(256 * 1024, gt=0)
    body_bytes: int = Field(11 * 1024 * 1024, gt=0)
    pdf_pages: int = Field(150, gt=0)
    questions_limit: int = Field(20, gt=0)
    question_chars: int = Field(2000, gt=0)
    json_depth: int = Field(32, gt=0)
    json_nodes: int = Field(100_000, gt=0)
    extracted_bytes: int = Field(10 * 1024 * 1024, gt=0)
    chunk_limit: int = Field(2000, gt=0)
    chunk_tokens: int = Field(700, ge=100)
    chunk_overlap: int = Field(100, ge=0)
    top_k: int = Field(6, gt=0)
    evidence_tokens: int = Field(6000, gt=0)
    context_neighbors: bool = True
    contextual_embeddings: bool = False
    provider_concurrency: int = Field(4, ge=1, le=16)
    provider_timeout: float = Field(30, gt=0)
    extraction_timeout: float = Field(90, gt=0)
    request_timeout: float = Field(180, gt=0)
    pdf_concurrency: int = Field(1, ge=1, le=2)
    vision_enabled: bool = False
    vision_crops: int = Field(3, ge=1, le=3)
    answer_images: int = Field(2, ge=1, le=2)

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def empty_key_is_unconfigured(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value
