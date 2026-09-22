import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, BookMarked, Check, Cloud, Database, FileText, Plus, RefreshCw, Search, Trash2, Upload, X, Zap } from 'lucide-react'
import { API, api, apiForm } from '../lib/api'
import type { KnowledgeDocument, KnowledgeDomain, RagHealth } from '../types'

const processing = new Set(['UPLOADED', 'PARSING', 'CHUNKING', 'EMBEDDING', 'INDEXING'])

function bytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

export function KnowledgeCenter({ workspaceId, onClose, onDomainsChanged }: { workspaceId: string; onClose: () => void; onDomainsChanged: (domains: KnowledgeDomain[]) => void }) {
  const [domains, setDomains] = useState<KnowledgeDomain[]>([])
  const [selected, setSelected] = useState('')
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([])
  const [health, setHealth] = useState<RagHealth | null>(null)
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const selectedRef = useRef('')

  const refresh = useCallback(async (preferredDomain?: string) => {
    const nextDomains = await api<KnowledgeDomain[]>(`/api/knowledge/domains?workspace_id=${encodeURIComponent(workspaceId)}`)
    setDomains(nextDomains); onDomainsChanged(nextDomains)
    const requested = preferredDomain || selectedRef.current
    const domain = nextDomains.some(item => item.id === requested) ? requested : nextDomains[0]?.id || ''
    selectedRef.current = domain
    setSelected(domain)
    setDocuments(domain ? await api<KnowledgeDocument[]>(`/api/knowledge/documents?workspace_id=${encodeURIComponent(workspaceId)}&domain_id=${encodeURIComponent(domain)}`) : [])
  }, [workspaceId, onDomainsChanged])

  useEffect(() => { selectedRef.current = ''; setSelected(''); setDocuments([]); setError('') }, [workspaceId])
  useEffect(() => { void refresh().catch(e => setError(String(e))) }, [refresh])
  useEffect(() => { void api<RagHealth>('/api/knowledge/health').then(setHealth).catch(e => setError(String(e))) }, [])
  useEffect(() => {
    if (!documents.some(doc => processing.has(doc.status))) return
    const timer = setInterval(() => { void refresh().catch(() => undefined) }, 2000)
    return () => clearInterval(timer)
  }, [documents, refresh])

  async function choose(domainId: string) {
    selectedRef.current = domainId
    setSelected(domainId); setError('')
    try { setDocuments(await api<KnowledgeDocument[]>(`/api/knowledge/documents?workspace_id=${encodeURIComponent(workspaceId)}&domain_id=${encodeURIComponent(domainId)}`)) }
    catch (e) { setError(String(e)) }
  }
  async function createDomain() {
    const response = window.prompt('Knowledge domain name')
    if (response === null) return
    const name = response.trim()
    if (!name) {
      setError('Enter a domain name, such as Finance, HR, Legal, or Operations.')
      return
    }
    try {
      const created = await api<KnowledgeDomain>(`/api/knowledge/domains?workspace_id=${encodeURIComponent(workspaceId)}`, 'POST', { name })
      selectedRef.current = created.id
      setSelected(created.id); await refresh(created.id); setError('')
    } catch (e) { setError(String(e)) }
  }
  async function initialize() {
    setBusy(true); setError('')
    try { await api('/api/knowledge/initialize', 'POST'); setHealth(await api<RagHealth>('/api/knowledge/health')); await refresh() }
    catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  async function upload(file?: File) {
    if (!file) return
    const domain = domains.find(item => item.id === selected)
    if (!domain) {
      setError('Create and select a knowledge domain before uploading a document.')
      return
    }
    const body = new FormData()
    body.append('workspace_id', workspaceId); body.append('domain_id', domain.id); body.append('file', file)
    setBusy(true); setError('')
    try {
      await api(`/api/knowledge/domains/${encodeURIComponent(domain.id)}?workspace_id=${encodeURIComponent(workspaceId)}`)
      await apiForm('/api/knowledge/documents/upload', body)
      await refresh(domain.id)
    }
    catch (e) { setError(String(e)) } finally { setBusy(false); if (input.current) input.current.value = '' }
  }
  async function reindex(id: string) {
    try { await api(`/api/knowledge/documents/${id}/reindex?workspace_id=${encodeURIComponent(workspaceId)}`, 'POST'); await refresh() }
    catch (e) { setError(String(e)) }
  }
  async function removeDomain(domain: KnowledgeDomain) {
    const documents = domain.document_count || 0
    const warning = documents
      ? `Delete "${domain.name}" and its ${documents} document${documents === 1 ? '' : 's'} from Blob Storage and Cosmos DB? This cannot be undone.`
      : `Delete the "${domain.name}" knowledge domain? This cannot be undone.`
    if (!window.confirm(warning)) return
    setBusy(true); setError('')
    try {
      await api(`/api/knowledge/domains/${domain.id}?workspace_id=${encodeURIComponent(workspaceId)}`, 'DELETE')
      if (selectedRef.current === domain.id) selectedRef.current = ''
      await refresh()
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  async function remove(document: KnowledgeDocument) {
    if (!window.confirm(`Delete "${document.file_name}" from Blob Storage and the Cosmos knowledge index?`)) return
    try { await api(`/api/knowledge/documents/${document.id}?workspace_id=${encodeURIComponent(workspaceId)}`, 'DELETE'); await refresh() }
    catch (e) { setError(String(e)) }
  }
  const filtered = documents.filter(doc => doc.file_name.toLowerCase().includes(query.toLowerCase()))
  return <div className="modal-backdrop"><section className="knowledge-modal" role="dialog" aria-modal="true" aria-label="Knowledge Center">
    <div className="library-header"><div><span className="eyebrow">AZURE RAG</span><h2><BookMarked size={24}/> Knowledge Center</h2></div><button className="icon-button" aria-label="Close knowledge center" onClick={onClose}><X size={20}/></button></div>
    <p className="library-intro">Curate workspace knowledge in Azure Blob Storage and Cosmos DB. Every retrieval is isolated to this workspace.</p>
    {error && <div className="error-banner" role="alert">{error}<button onClick={() => setError('')}><X size={14}/></button></div>}
    <div className="rag-health"><strong>RAG Infrastructure</strong>{health ? Object.entries(health.services).map(([name, item]) => <div key={name} className={item.status === 'connected' ? 'healthy' : 'unhealthy'}>{name === 'cosmos' ? <Database size={15}/> : name === 'blob' ? <Cloud size={15}/> : <Zap size={15}/>}<span>{name === 'cosmos' ? 'Cosmos DB' : name === 'blob' ? 'Blob Storage' : 'Embedding service'}</span>{item.status === 'connected' ? <><Check size={14}/><small>{item.latency_ms} ms</small></> : <><AlertTriangle size={14}/><small>{item.reason}</small></>}</div>) : <span>Checking...</span>}<button disabled={busy} onClick={() => void initialize()}>Initialize safely</button></div>
    <div className="knowledge-toolbar"><div><strong>Domains</strong><div className="domain-tabs">{domains.map(domain => <div className={`domain-tab ${selected === domain.id ? 'active' : ''}`} key={domain.id}><button className="domain-select" onClick={() => void choose(domain.id)}>{domain.name}<small>{domain.document_count || 0} docs</small></button><button className="domain-delete" title={`Delete ${domain.name}`} aria-label={`Delete ${domain.name} domain`} disabled={busy} onClick={() => void removeDomain(domain)}><Trash2 size={12}/></button></div>)}<button className="new-domain" onClick={() => void createDomain()}><Plus size={14}/> New domain</button></div></div><button className="primary" disabled={!selected || busy} onClick={() => input.current?.click()}><Upload size={15}/> {busy ? 'Working...' : 'Upload'}</button><input ref={input} hidden type="file" accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.json" onChange={e => void upload(e.target.files?.[0])}/></div>
    <div className="document-heading"><div><strong>Documents</strong><span>{domains.find(item => item.id === selected)?.name || 'Select a domain'}</span></div><label className="search"><Search size={14}/><input aria-label="Search knowledge documents" placeholder="Filter documents" value={query} onChange={e => setQuery(e.target.value)}/></label></div>
    <div className="knowledge-documents">{filtered.map(document => <article key={document.id}><div className="document-icon"><FileText size={20}/></div><div className="document-info"><strong>{document.file_name}</strong><span>{bytes(document.file_size)}{document.page_count ? ` - ${document.page_count} pages` : ''}{document.chunk_count ? ` - ${document.chunk_count} chunks` : ''}</span>{processing.has(document.status) && <div className="progress"><i style={{width: `${document.progress}%`}}/></div>}{document.error && <small className="document-error">{document.error}</small>}</div><span className={`status-badge ${document.status.toLowerCase()}`}>{document.status.replace('_', ' ')}</span><div className="document-actions"><a title="Open source" href={`${API}/api/knowledge/documents/${document.id}/content?workspace_id=${encodeURIComponent(workspaceId)}`} target="_blank" rel="noreferrer">View</a><button title="Reindex" disabled={processing.has(document.status)} onClick={() => void reindex(document.id)}><RefreshCw size={14}/></button><button title="Delete" onClick={() => void remove(document)}><Trash2 size={14}/></button></div></article>)}{selected && !filtered.length && <div className="knowledge-empty"><Upload size={30}/><strong>No documents yet</strong><span>Upload a PDF, DOCX, text, Markdown, CSV, XLSX, or JSON file.</span></div>}{!selected && <div className="knowledge-empty"><BookMarked size={30}/><strong>Create a domain to begin</strong><span>Domains keep knowledge organized inside this workspace.</span></div>}</div>
  </section></div>
}
