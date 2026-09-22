import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, LoaderCircle } from 'lucide-react'
import { API, api } from '../../lib/api'
import { ScreenshotViewer } from './ScreenshotViewer'
import type { ScreenshotMode } from '../../types'
export function ScreenshotPreview({ sessionId, workspaceId, version }: { sessionId: string; workspaceId: string; version: number }) {
  const [mode, setMode] = useState<ScreenshotMode>('viewport')
  const [captureVersion, setCaptureVersion] = useState(version)
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const close = useCallback(() => setExpanded(false), [])
  useEffect(() => {
    let stale = false
    if (mode === 'viewport' && retry === 0) { setCaptureVersion(version); setBusy(false); setError(''); return }
    setBusy(true); setError('')
    void api<{ version: number }>('/api/browser/screenshot', 'POST', { session_id: sessionId, workspace_id: workspaceId, mode }).then(result => { if (!stale) setCaptureVersion(result.version) }).catch(e => { if (!stale) setError(String(e)) }).finally(() => { if (!stale) setBusy(false) })
    return () => { stale = true }
  }, [sessionId, workspaceId, mode, version, retry])
  const src = `${API}/api/browser/screenshot?session_id=${sessionId}&workspace_id=${encodeURIComponent(workspaceId)}&mode=${mode}&v=${captureVersion}`
  return <section className="screenshot-preview"><div className="capture-options"><div><button className={mode === 'viewport' ? 'active' : ''} onClick={() => { setRetry(0); setMode('viewport') }}>Viewport</button><button className={mode === 'full_page' ? 'active' : ''} onClick={() => { setRetry(0); setMode('full_page') }}>Full page</button></div><button aria-label="Refresh screenshot" disabled={busy} onClick={() => setRetry(r => r + 1)}>{busy ? <LoaderCircle size={13} className="spin"/> : <RefreshCw size={13}/>}</button></div>{error ? <div className="capture-error" role="alert"><p>Unable to capture {mode === 'full_page' ? 'full-page' : 'viewport'} screenshot.</p><small>{error}</small><button onClick={() => setRetry(r => r + 1)}>Retry</button></div> : busy ? <div className="capture-loading"><LoaderCircle className="spin" size={20}/> Capturing the real pageâ€¦</div> : <ScreenshotViewer src={src} onExpand={() => setExpanded(true)}/>} {expanded && !busy && !error && <div className="viewer-backdrop"><ScreenshotViewer src={src} expanded onClose={close}/></div>}</section>
}

