# Azure RAG knowledge system

Orbit stores original knowledge documents in Azure Blob Storage and metadata, chunks, and vectors in Azure Cosmos DB for NoSQL. It does not use a local or third-party vector database.

## Required Azure capabilities

- An Azure Cosmos DB for NoSQL account with vector search enabled.
- A dedicated database/container for Orbit knowledge. The container partition key is /workspace_id.
- The container vector embedding policy uses /embedding, float32, cosine distance, and the exact dimension in RAG_EMBEDDING_DIMENSIONS.
- The indexing policy excludes /embedding/* from the normal index and adds a quantizedFlat vector index at /embedding.
- An Azure Blob Storage container for original files.
- An Azure OpenAI or OpenAI embedding deployment/model. For Azure, RAG_EMBEDDING_MODEL is the embedding deployment name.

Use a dedicated RAG container. The initializer never deletes or recreates an existing resource and therefore cannot retrofit a different vector policy onto an existing container.

## Configuration

Copy the RAG variables from .env.example into .env:

    AZURE_COSMOS_ENDPOINT=
    AZURE_COSMOS_KEY=
    AZURE_COSMOS_DATABASE=orbit-rag
    AZURE_COSMOS_CONTAINER=knowledge
    AZURE_BLOB_CONNECTION_STRING=
    AZURE_BLOB_CONTAINER=knowledge
    AZURE_BLOB_ACCOUNT_URL=
    AZURE_BLOB_ACCOUNT_NAME=
    AZURE_BLOB_SAS_TOKEN=
    AZURE_STORAGE_ACCOUNT_NAME=
    AZURE_STORAGE_ACCOUNT_KEY=
    AZURE_STORAGE_CONNECTION_STRING=
    AZURE_STORAGE_CONTAINER_NAME=
    RAG_EMBEDDING_PROVIDER=azure
    RAG_EMBEDDING_MODEL=text-embedding-3-small
    RAG_EMBEDDING_DIMENSIONS=1536
    RAG_AZURE_OPENAI_API_KEY=
    RAG_AZURE_OPENAI_ENDPOINT=
    RAG_AZURE_OPENAI_API_VERSION=2024-10-21
    RAG_TOP_K=8
    RAG_CANDIDATE_K=24
    RAG_MIN_SCORE=0.15
    RAG_CHUNK_SIZE=750
    RAG_CHUNK_OVERLAP=100
    RAG_MAX_CONTEXT_TOKENS=6000
    RAG_EMBEDDING_BATCH_SIZE=16
    RAG_MAX_UPLOAD_BYTES=50000000
    RAG_MAX_QUERIES=3
    RAG_BACKGROUND_CONCURRENCY=2
    DEBUG_RAG=false

The AZURE_STORAGE_* names are accepted as aliases for the AZURE_BLOB_* names. Dedicated RAG_AZURE_OPENAI_* credentials take precedence for embeddings, while the existing chat Azure OpenAI credentials remain a fallback. Credentials stay on the backend and are never returned to the browser. The storage adapters are isolated so a future managed-identity credential can replace key/SAS authentication without changing ingestion or retrieval.

## Safe initialization

After configuring .env, initialize the resources explicitly:

    cd backend
    .\.venv\Scripts\python.exe scripts\init_rag.py

The same idempotent operation is available from the Knowledge Center and POST /api/knowledge/initialize. It creates missing configured resources and reuses existing ones. It never deletes, recreates, or changes unrelated Azure resources.

## Cosmos item model and partitioning

One container stores three item kinds:

- domain: workspace-owned knowledge-domain metadata.
- document: Blob path, hash, type, size, status, version, and indexing metadata.
- chunk: normalized text, source metadata, chunk hash, embedding model, and vector.

/workspace_id is the partition key because a workspace is the stable tenant boundary and every request is scoped to exactly one workspace. Domain and document filters then operate inside that logical partition. This avoids cross-workspace vector retrieval while keeping a workspace query single-partition. Very large tenants can later move to a hierarchical partition strategy after measuring their workload; changing partition keys requires a new container.

Blob paths are:

    {workspace_id}/{domain_id}/{document_id}/v{version}/{safe_file_name}

## Ingestion flow

1. Validate the workspace and domain server-side.
2. Validate type/size and calculate SHA-256.
3. Reject duplicate content in the same workspace/domain.
4. Upload the original to Blob Storage.
5. Persist UPLOADED metadata and return HTTP 202.
6. Continue in a bounded background task through PARSING, CHUNKING, EMBEDDING, INDEXING, and READY.
7. Parse PDF, DOCX, TXT, Markdown, CSV, XLSX, or JSON into structured blocks.
8. Preserve real page/section metadata, create overlapping structure-aware chunks, batch embeddings, and upsert chunks.

Image-only PDFs become OCR_REQUIRED; the system does not claim OCR occurred. In-process background jobs survive closing the UI, but not a backend process restart. A durable Azure queue/worker is the remaining production-hardening step for restart recovery.

## Retrieval flow

The query is embedded, searched with Cosmos VectorDistance, and always filtered by workspace_id. An explicit domain adds a mandatory domain_id filter. Optional document and content-type filters are applied in Cosmos. Candidate results are deduplicated, lightly reranked using vector similarity plus lexical overlap, thresholded, and assembled within RAG_MAX_CONTEXT_TOKENS.

The existing agent calls rag_search automatically for workspace-specific requests. Selecting a domain or all-workspace knowledge performs retrieval before model generation. Selecting Off removes the RAG tool. A skill may add knowledge_domain to its existing YAML metadata.

Only retrieved chunks become citations. Citation previews fetch one validated chunk from the backend; Blob credentials and vectors are never exposed.

## API

- GET /api/knowledge/health
- POST /api/knowledge/initialize
- GET|POST /api/knowledge/domains
- GET /api/knowledge/domains/{domain_id}
- POST /api/knowledge/documents/upload
- GET /api/knowledge/documents
- GET /api/knowledge/documents/{document_id}
- GET /api/knowledge/documents/{document_id}/status
- POST /api/knowledge/documents/{document_id}/reindex
- DELETE /api/knowledge/documents/{document_id}
- GET /api/knowledge/documents/{document_id}/content
- GET /api/knowledge/sources/{chunk_id}
- POST /api/knowledge/query
- GET /api/knowledge/metrics

## Troubleshooting

- authentication: verify the Cosmos key or Blob connection string/SAS and service permissions.
- endpoint: verify account URLs and DNS/network access.
- database / container: run the initializer or verify configured names.
- Embedding failure: for Azure, use the embedding deployment name rather than the base model name and match its vector dimensions.
- Existing container fails vector queries: verify vector search is enabled and create a dedicated container with the documented vector policy.
- OCR_REQUIRED: configure a future OCR provider or upload a text-searchable PDF.

Set DEBUG_RAG=true only in development to include rewritten queries, selected chunk IDs/scores, and context size in retrieval responses. Secrets and full documents are never logged.
