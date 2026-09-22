from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from pydantic import BaseModel, ConfigDict, Field


class DomainCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default='', max_length=500)


class KnowledgeQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    workspace_id: str
    query: str = Field(min_length=2, max_length=8000)
    domain_id: str | None = None
    document_id: str | None = None
    content_type: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=30)


class RagSearchArgs(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=2, max_length=8000, description='The workspace-specific question or search phrase.')
    queries: list[str] = Field(default_factory=list, max_length=4, description='Optional alternate search phrases for a complex question.')
    document_id: str | None = Field(default=None, description='Optional document UUID filter.')
    content_type: str | None = Field(default=None, description='Optional MIME type filter.')


@dataclass(slots=True)
class Block:
    text: str
    page_number: int | None = None
    section: str | None = None
    kind: str = 'paragraph'


@dataclass(slots=True)
class ParsedDocument:
    blocks: list[Block]
    page_count: int | None = None


@dataclass(slots=True)
class Chunk:
    text: str
    chunk_index: int
    page_number: int | None = None
    section: str | None = None
    chunk_hash: str = ''


@dataclass(slots=True)
class RetrievalResult:
    chunks: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    context: str
    query_id: str
    debug: dict[str, Any] | None = None


class EmbeddingProvider(Protocol):
    @property
    def available(self) -> bool: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class BlobStore(Protocol):
    async def upload(self, path: str, data: bytes, content_type: str) -> None: ...
    async def download(self, path: str) -> bytes: ...
    async def delete(self, path: str) -> None: ...
    async def health(self) -> None: ...


class VectorStore(Protocol):
    async def health(self) -> None: ...
    async def initialize(self) -> dict[str, Any]: ...
    async def upsert(self, item: dict[str, Any]) -> None: ...
    async def get(self, item_id: str, workspace_id: str) -> dict[str, Any] | None: ...
    async def delete(self, item_id: str, workspace_id: str) -> None: ...
    async def query_items(self, query: str, parameters: list[dict[str, Any]], workspace_id: str) -> list[dict[str, Any]]: ...
    async def vector_search(self, workspace_id: str, embedding: list[float], limit: int, filters: dict[str, str | None]) -> list[dict[str, Any]]: ...
