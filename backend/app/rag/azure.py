from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote
from app.config import settings


def _transient(exc: Exception) -> bool:
    status = getattr(exc, 'status_code', None)
    return status in {408, 409, 429, 500, 502, 503, 504} or isinstance(exc, (TimeoutError, ConnectionError))


async def retry(operation, attempts: int = 4):
    for attempt in range(attempts):
        try:
            return await operation()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if attempt == attempts - 1 or not _transient(exc):
                raise
            await asyncio.sleep(min(0.5 * (2 ** attempt), 4))


class AzureBlobStore:
    @staticmethod
    def container_name():
        return settings.azure_storage_container_name or settings.azure_blob_container

    def _service(self):
        from azure.storage.blob.aio import BlobServiceClient
        connection_string = settings.azure_storage_connection_string or settings.azure_blob_connection_string
        if connection_string:
            return BlobServiceClient.from_connection_string(connection_string)
        account_url = settings.azure_blob_account_url
        account_name = settings.azure_storage_account_name or settings.azure_blob_account_name
        if not account_url and account_name:
            account_url = f'https://{account_name}.blob.core.windows.net'
        if not account_url:
            raise RuntimeError('Azure Blob Storage is not configured.')
        credential = settings.azure_storage_account_key or settings.azure_blob_sas_token or None
        return BlobServiceClient(account_url=account_url, credential=credential)

    async def health(self) -> None:
        async with self._service() as client:
            await client.get_container_client(self.container_name()).get_container_properties()

    async def initialize(self) -> dict[str, Any]:
        from azure.core.exceptions import ResourceExistsError
        async with self._service() as client:
            container = client.get_container_client(self.container_name())
            try:
                await container.create_container()
                created = True
            except ResourceExistsError:
                created = False
            return {'container': self.container_name(), 'created': created}

    async def upload(self, path: str, data: bytes, content_type: str) -> None:
        from azure.storage.blob import ContentSettings
        async def perform():
            async with self._service() as client:
                blob = client.get_blob_client(self.container_name(), path)
                await blob.upload_blob(data, overwrite=False, content_settings=ContentSettings(content_type=content_type))
        await retry(perform)

    async def download(self, path: str) -> bytes:
        async def perform():
            async with self._service() as client:
                stream = await client.get_blob_client(self.container_name(), path).download_blob()
                return await stream.readall()
        return await retry(perform)

    async def delete(self, path: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError
        async def perform():
            async with self._service() as client:
                try:
                    await client.get_blob_client(self.container_name(), path).delete_blob()
                except ResourceNotFoundError:
                    return
        await retry(perform)


class CosmosVectorStore:
    @staticmethod
    def _validate_schema(properties: dict[str, Any]) -> None:
        partition_paths = (properties.get('partitionKey') or {}).get('paths') or []
        if partition_paths != ['/workspace_id']:
            raise RuntimeError(
                'Cosmos knowledge container schema mismatch: partition key must be /workspace_id.'
            )

        embeddings = (properties.get('vectorEmbeddingPolicy') or {}).get('vectorEmbeddings') or []
        embedding = next((item for item in embeddings if item.get('path') == '/embedding'), None)
        if not embedding or embedding.get('dimensions') != settings.rag_embedding_dimensions:
            raise RuntimeError(
                'Cosmos knowledge container schema mismatch: /embedding vector dimensions do not match configuration.'
            )

        vector_indexes = (properties.get('indexingPolicy') or {}).get('vectorIndexes') or []
        if not any(item.get('path') == '/embedding' for item in vector_indexes):
            raise RuntimeError(
                'Cosmos knowledge container schema mismatch: /embedding vector index is missing.'
            )

    def _client(self):
        from azure.cosmos.aio import CosmosClient
        if not settings.azure_cosmos_endpoint or not settings.azure_cosmos_key:
            raise RuntimeError('Azure Cosmos DB is not configured.')
        return CosmosClient(settings.azure_cosmos_endpoint, credential=settings.azure_cosmos_key)

    async def _container(self):
        client = self._client()
        database = client.get_database_client(settings.azure_cosmos_database)
        return client, database.get_container_client(settings.azure_cosmos_container)

    async def health(self) -> None:
        client, container = await self._container()
        try:
            self._validate_schema(await container.read())
        finally:
            await client.close()

    async def initialize(self) -> dict[str, Any]:
        from azure.cosmos import PartitionKey
        client = self._client()
        try:
            database = await client.create_database_if_not_exists(settings.azure_cosmos_database)
            indexing_policy = {
                'indexingMode': 'consistent',
                'automatic': True,
                'includedPaths': [{'path': '/*'}],
                'excludedPaths': [{'path': '/"_etag"/?'}, {'path': '/embedding/*'}],
                'vectorIndexes': [{'path': '/embedding', 'type': 'quantizedFlat'}],
            }
            vector_policy = {
                'vectorEmbeddings': [{
                    'path': '/embedding',
                    'dataType': 'float32',
                    'distanceFunction': 'cosine',
                    'dimensions': settings.rag_embedding_dimensions,
                }]
            }
            container = await database.create_container_if_not_exists(
                id=settings.azure_cosmos_container,
                partition_key=PartitionKey(path='/workspace_id'),
                indexing_policy=indexing_policy,
                vector_embedding_policy=vector_policy,
            )
            properties = await container.read()
            self._validate_schema(properties)
            return {
                'database': settings.azure_cosmos_database,
                'container': settings.azure_cosmos_container,
                'partition_key': '/workspace_id',
                'vector_path': '/embedding',
                'dimensions': settings.rag_embedding_dimensions,
                'resource_id': properties.get('_rid', ''),
            }
        finally:
            await client.close()

    async def upsert(self, item: dict[str, Any]) -> None:
        client, container = await self._container()
        try:
            await retry(lambda: container.upsert_item(item))
        finally:
            await client.close()

    async def upsert_many(self, items: list[dict[str, Any]], concurrency: int = 8) -> None:
        if not items:
            return
        client, container = await self._container()
        gate = asyncio.Semaphore(max(1, concurrency))

        async def upsert_one(item: dict[str, Any]) -> None:
            async with gate:
                await retry(lambda: container.upsert_item(item))

        try:
            await asyncio.gather(*(upsert_one(item) for item in items))
        finally:
            await client.close()

    async def get(self, item_id: str, workspace_id: str) -> dict[str, Any] | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError
        client, container = await self._container()
        try:
            try:
                return await container.read_item(item_id, partition_key=workspace_id)
            except CosmosResourceNotFoundError:
                return None
        finally:
            await client.close()

    async def delete(self, item_id: str, workspace_id: str) -> None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError
        client, container = await self._container()
        try:
            try:
                await retry(lambda: container.delete_item(item_id, partition_key=workspace_id))
            except CosmosResourceNotFoundError:
                return
        finally:
            await client.close()

    async def query_items(self, query: str, parameters: list[dict[str, Any]], workspace_id: str) -> list[dict[str, Any]]:
        client, container = await self._container()
        try:
            iterator = container.query_items(
                query=query, parameters=parameters, partition_key=workspace_id,
            )
            return [item async for item in iterator]
        finally:
            await client.close()

    async def vector_search(self, workspace_id: str, embedding: list[float], limit: int, filters: dict[str, str | None]) -> list[dict[str, Any]]:
        where = ["c.workspace_id = @workspace_id", "c.kind = 'chunk'"]
        parameters: list[dict[str, Any]] = [
            {'name': '@workspace_id', 'value': workspace_id},
            {'name': '@embedding', 'value': embedding},
        ]
        for name in ('domain_id', 'document_id', 'content_type'):
            value = filters.get(name)
            if value:
                where.append(f'c.{name} = @{name}')
                parameters.append({'name': f'@{name}', 'value': value})
        query = (
            f'SELECT TOP {int(limit)} c.id, c.document_id, c.domain_id, c.chunk_index, c.text, '
            'c.page_number, c.section, c.source_file, c.content_type, '
            'VectorDistance(c.embedding, @embedding) AS distance '
            f"FROM c WHERE {' AND '.join(where)} ORDER BY VectorDistance(c.embedding, @embedding)"
        )
        return await self.query_items(query, parameters, workspace_id)

    async def delete_document_items(self, workspace_id: str, document_id: str) -> None:
        rows = await self.query_items(
            "SELECT c.id FROM c WHERE c.workspace_id=@workspace_id AND c.document_id=@document_id",
            [{'name': '@workspace_id', 'value': workspace_id}, {'name': '@document_id', 'value': document_id}],
            workspace_id,
        )
        for row in rows:
            await self.delete(row['id'], workspace_id)

    async def delete_workspace_items(self, workspace_id: str) -> None:
        rows = await self.query_items(
            'SELECT c.id FROM c WHERE c.workspace_id=@workspace_id',
            [{'name': '@workspace_id', 'value': workspace_id}],
            workspace_id,
        )
        for row in rows:
            await self.delete(row['id'], workspace_id)
