from __future__ import annotations

import asyncio
from openai import AsyncAzureOpenAI, AsyncOpenAI
from app.config import settings
from app.rag.azure import retry


class OpenAIEmbeddingProvider:
    @property
    def available(self) -> bool:
        if settings.rag_embedding_provider == 'azure':
            api_key = settings.rag_azure_openai_api_key or settings.azure_openai_api_key
            endpoint = settings.rag_azure_openai_endpoint or settings.azure_openai_endpoint
            return bool(api_key and endpoint and settings.rag_embedding_model)
        return bool(settings.openai_api_key and settings.rag_embedding_model)

    def _client(self):
        if settings.rag_embedding_provider == 'azure':
            return AsyncAzureOpenAI(
                api_key=settings.rag_azure_openai_api_key or settings.azure_openai_api_key,
                azure_endpoint=settings.rag_azure_openai_endpoint or settings.azure_openai_endpoint,
                api_version=settings.rag_azure_openai_api_version or settings.azure_openai_api_version,
            )
        if settings.rag_embedding_provider == 'openai':
            return AsyncOpenAI(api_key=settings.openai_api_key)
        raise RuntimeError('RAG_EMBEDDING_PROVIDER must be azure or openai.')

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.available:
            raise RuntimeError('The RAG embedding provider is not configured.')
        if not texts:
            return []

        async def perform():
            async with self._client() as client:
                response = await client.embeddings.create(
                    model=settings.rag_embedding_model,
                    input=texts,
                    dimensions=settings.rag_embedding_dimensions,
                )
                ordered = sorted(response.data, key=lambda item: item.index)
                vectors = [item.embedding for item in ordered]
                if any(len(vector) != settings.rag_embedding_dimensions for vector in vectors):
                    raise RuntimeError('Embedding dimensions do not match RAG_EMBEDDING_DIMENSIONS.')
                return vectors
        return await retry(perform)

    async def health(self) -> None:
        vectors = await self.embed(['knowledge infrastructure health check'])
        if not vectors:
            raise RuntimeError('Embedding service returned no vector.')
