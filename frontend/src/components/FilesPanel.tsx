import { useEffect, useState } from 'react'
import { Folder, FileText, ArrowLeft, X, ShieldCheck } from 'lucide-react'
import { api } from '../lib/api'
interface Listing { path: string; entries: { name: string; kind: string; bytes: number | null }[] }
export function FilesPanel({ workspaceId, onClose }: { workspaceId: string; onClose: () => void }) {
  const [root, setRoot] = useState('')
  const [path, setPath] = useState('.')
  const [listing, setListing] = useState<Listing | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { void api<{ workspace: string }>(`/api/files/status?workspace_id=${encodeURIComponent(workspaceId)}`).then(r => setRoot(r.workspace)).catch(e => setError(String(e))) }, [workspaceId])
  useEffect(() => { let stale = false; setError(''); void api<Listing>(`/api/files?path=${encodeURIComponent(path)}&workspace_id=${encodeURIComponent(workspaceId)}`).then(r => { if (!stale) setListing(r) }).catch(e => { if (!stale) setError(String(e)) }); return () => { stale = true } }, [path, workspaceId])
  return <div className="modal-backdrop"><section className="files-modal" role="dialog" aria-modal="true" aria-label="File workspace"><div className="library-header"><div><span className="eyebrow">LOCAL FILE AGENT</span><h2><Folder size={23}/> Your file workspace</h2></div><button className="icon-button" aria-label="Close files" onClick={onClose}><X size={20}/></button></div><p className="workspace-path">{root}</p><div className="file-policy"><ShieldCheck size={16}/><span>Only this folder is allowed. Downloads, Documents, and Desktop are not granted.</span></div><div className="file-breadcrumb"><button disabled={path === '.'} onClick={() => setPath(path.split('/').slice(0, -1).join('/') || '.')}><ArrowLeft size={14}/></button><span>Workspace / {path === '.' ? '' : path}</span></div>{error && <div className="error-banner">{error}</div>}<div className="file-list">{listing?.entries.map(entry => <button key={entry.name} disabled={entry.kind !== 'folder'} onClick={() => setPath((path === '.' ? '' : path + '/') + entry.name)}>{entry.kind === 'folder' ? <Folder size={17}/> : <FileText size={17}/>}<span>{entry.name}</span><small>{entry.kind === 'folder' ? 'Folder' : `${(entry.bytes! / 1024).toFixed(1)} KB`}</small></button>)}{listing && !listing.entries.length && <div className="files-empty">A clear workspace.<br/><small>Ask Orbit to create a folder or save your next report here.</small></div>}</div><div className="library-tip">Try: â€œCreate a folder named reports and save a summary as report.txt.â€</div></section></div>
}


