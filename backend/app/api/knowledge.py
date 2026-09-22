from __future__ import annotations

import io
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from app.config import settings
from app.database.store import DEFAULT_WORKSPACE_ID
from app.rag.models import DomainCreate, KnowledgeQuery
from app.rag.service import rag_service

router = APIRouter(prefix='/api/knowledge', tags=['knowledge'])


def problem(exc: Exception, status: int = 400):
    if not isinstance(exc, ValueError):
        return HTTPException(503, 'Knowledge service unavailable. Check RAG Infrastructure health for safe diagnostics.')
    message = str(exc)
    if 'not found' in message.lower():
        status = 404
    elif 'duplicate' in message.lower() or 'already processing' in message.lower():
        status = 409
    elif 'supported formats' in message.lower():
        status = 415
    return HTTPException(status, message)


@router.get('/health')
async def health():
    return await rag_service.health()


@router.post('/initialize')
async def initialize():
    try:
        return await rag_service.initialize()
    except Exception as exc:
        message = str(exc).lower()
        if 'vector policy' in message and 'capability' in message:
            raise HTTPException(
                503,
                'Cosmos DB Vector Search is not enabled for this account. Enable the capability in Azure, then click Initialize safely again.',
            ) from exc
        raise HTTPException(503, 'Unable to initialize the configured RAG resources. Check endpoint, credentials, database/container names, vector support, and permissions.') from exc


@router.get('/metrics')
async def metrics():
    return rag_service.metrics.snapshot()


@router.post('/domains')
async def create_domain(body: DomainCreate, workspace_id: str = DEFAULT_WORKSPACE_ID):
    try:
        return await rag_service.create_domain(workspace_id, body.name, body.description)
    except Exception as exc:
        raise problem(exc) from exc


@router.get('/domains')
async def domains(workspace_id: str = DEFAULT_WORKSPACE_ID):
    try:
        return await rag_service.list_domains(workspace_id)
    except Exception as exc:
        raise problem(exc) from exc


@router.get('/domains/{domain_id}')
async def domain(domain_id: str, workspace_id: str = DEFAULT_WORKSPACE_ID):
    try:
        item = await rag_service.require_domain(rag_service.require_workspace(workspace_id), domain_id)
        return {**item, 'documents': await rag_service.list_documents(workspace_id, domain_id)}
    except Exception as exc:
        raise problem(exc) from exc


@router.delete('/domains/{domain_id}')
async def delete_domain(domain_id: str, workspace_id: str = DEFAULT_WORKSPACE_ID):
    try:
        return await rag_service.delete_domain(workspace_id, domain_id)
    except Exception as exc:
        raise problem(exc, 503) from exc


@router.post('/documents/upload', status_code=202)
async def upload_document(
    workspace_id: str = Form(...),
    domain_id: str = Form(...),
    file: UploadFile = File(...),
):
    try:
        data = await file.read(settings.rag_max_upload_bytes + 1)
        return await rag_service.upload(workspace_id, domain_id, file.filename or 'document', file.content_type or '', data)
    except Exception as exc:
        raise problem(exc) from exc
    finally:
        await file.close()


@router.get('/documents')
async def documents(workspace_id: str = DEFAULT_WORKSPACE_ID, domain_id: str | None = None):
    try:
        return await rag_service.list_documents(workspace_id, domain_id)
    except Exception as exc:
        raise problem(exc) from exc


@router.get('/documents/{document_id}')
async def document(document_id: str, workspace_id: str = DEFAULT_WORKSPACE_ID):
    try:
        return await rag_service.get_document(workspace_id, document_id)
    except Exception as exc:
        raise problem(exc) from exc


@router.get('/documents/{document_id}/status')
async def document_status(document_id: str, workspace_id: str = DEFAULT_WORKSPACE_ID):
    try:
        document = await rag_service.get_document(workspace_id, document_id)
        return {key: document.get(key) for key in ('id', 'status', 'progress', 'chunk_count', 'page_count', 'error', 'updated_at', 'indexed_at')}
    except Exception as exc:
        raise problem(exc) from exc


@router.post('/documents/{document_id}/reindex', status_code=202)
async def reindex(document_id: str, workspace_id: str = DEFAULT_WORKSPACE_ID):
    try:
        return await rag_service.reindex(workspace_id, document_id)
    except Exception as exc:
        raise problem(exc) from exc


@router.delete('/documents/{document_id}')
async def delete_document(document_id: str, workspace_id: str = DEFAULT_WORKSPACE_ID):
    try:
        return await rag_service.delete_document(workspace_id, document_id)
    except Exception as exc:
        raise problem(exc, 503) from exc


@router.get('/documents/{document_id}/content')
async def download_document(document_id: str, workspace_id: str = DEFAULT_WORKSPACE_ID):
    try:
        document, data = await rag_service.download(workspace_id, document_id)
        headers = {'Content-Disposition': f'inline; filename="{document["file_name"]}"', 'Cache-Control': 'private, no-store'}
        return StreamingResponse(io.BytesIO(data), media_type=document['content_type'], headers=headers)
    except Exception as exc:
        raise problem(exc, 503) from exc


@router.get('/sources/{chunk_id}')
async def source_preview(chunk_id: str, workspace_id: str = DEFAULT_WORKSPACE_ID):
    try:
        return await rag_service.chunk_preview(workspace_id, chunk_id)
    except Exception as exc:
        raise problem(exc) from exc


@router.post('/query')
async def query(body: KnowledgeQuery):
    try:
        result = await rag_service.query(
            body.workspace_id, body.query, body.domain_id,
            document_id=body.document_id, content_type=body.content_type, top_k=body.top_k,
        )
        response = {
            'query_id': result.query_id, 'chunks': [
                {key: chunk.get(key) for key in ('id', 'document_id', 'domain_id', 'chunk_index', 'text', 'page_number', 'section', 'source_file', 'content_type', 'score')}
                for chunk in result.chunks
            ],
            'sources': result.sources, 'context': result.context,
        }
        if result.debug is not None:
            response['debug'] = result.debug
        return response
    except Exception as exc:
        raise problem(exc, 503) from exc
