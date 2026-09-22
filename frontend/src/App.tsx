import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUp, ArrowUpRight, Globe2, Plus, Search, Settings2, Square, Orbit, MessageSquare, Pencil, Trash2, PanelRightClose, Monitor, ShieldCheck, X, ChevronDown, Sparkles, ExternalLink, BookMarked, FileText } from 'lucide-react'
import { api } from './lib/api'
import { BookOpen, FolderOpen, Moon, Sun } from 'lucide-react'
import { ScreenshotPreview } from './components/browser/ScreenshotPreview'
import { SkillsPanel } from './components/SkillsPanel'
import { FilesPanel } from './components/FilesPanel'
import { KnowledgeCenter } from './components/KnowledgeCenter'
import { ActivityCard } from './components/ActivityCard'
import type { Activity, BrowserState, Confirmation, Conversation, Health, KnowledgeDomain, KnowledgeSource, Message, Provider, SourcePreview, Workspace } from './types'

const emptyBrowser: BrowserState = { status: 'closed', url: '', tabs: '', screenshot: 0 }
const defaultWorkspace = '00000000-0000-0000-0000-000000000001'
const prompts = [ ['Explore a website', 'Open example.com and describe what you find.'], ['Find something online', 'Open Google and search for Playwright MCP.'], ['Pick up where you left off', 'Inspect the current browser page and tell me what I can do next.'] ]

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [workspace, setWorkspace] = useState(() => localStorage.getItem('orbit-workspace') || defaultWorkspace)
  const [active, setActive] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [activity, setActivity] = useState<Activity[]>([])
  const [browser, setBrowser] = useState<BrowserState>(emptyBrowser)
  const [health, setHealth] = useState<Health | null>(null)
  const [provider, setProvider] = useState<Provider>(() => { const saved = localStorage.getItem(`orbit-provider-${workspace}`); return saved === 'openai' || saved === 'azure' || saved === 'anthropic' ? saved : 'azure' })
  const [input, setInput] = useState('')
  const [search, setSearch] = useState('')
  const [running, setRunning] = useState(false)
  const [partial, setPartial] = useState('')
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null)
  const [error, setError] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [preview, setPreview] = useState(true)
  const [connected, setConnected] = useState(false)
  const [skillsOpen, setSkillsOpen] = useState(false)
  const [filesOpen, setFilesOpen] = useState(false)
  const [knowledgeOpen, setKnowledgeOpen] = useState(false)
  const [knowledgeDomains, setKnowledgeDomains] = useState<KnowledgeDomain[]>([])
  const [knowledgeMode, setKnowledgeMode] = useState(() => localStorage.getItem(`orbit-knowledge-${workspace}`) || 'auto')
  const [sourcePreview, setSourcePreview] = useState<SourcePreview | null>(null)
  const [deletingWorkspace, setDeletingWorkspace] = useState(false)
  const [dark, setDark] = useState(() => localStorage.getItem('orbit-theme') === 'dark')
  useEffect(() => { document.documentElement.dataset.theme = dark ? 'dark' : 'light'; localStorage.setItem('orbit-theme', dark ? 'dark' : 'light') }, [dark])
  useEffect(() => { const saved = localStorage.getItem(`orbit-provider-${workspace}`); if (saved === 'openai' || saved === 'azure' || saved === 'anthropic') setProvider(saved) }, [workspace])
  useEffect(() => { localStorage.setItem(`orbit-provider-${workspace}`, provider) }, [provider, workspace])
  useEffect(() => { localStorage.setItem(`orbit-knowledge-${workspace}`, knowledgeMode) }, [knowledgeMode, workspace])
  const socket = useRef<WebSocket | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const refresh = useCallback(async () => setConversations(await api<Conversation[]>(`/api/conversations?workspace_id=${workspace}`)), [workspace])
  const refreshWorkspaces = useCallback(async () => { const available = await api<Workspace[]>('/api/workspaces'); setWorkspaces(available); setWorkspace(current => available.some(item => item.id === current) ? current : defaultWorkspace) }, [])
  useEffect(() => { localStorage.setItem('orbit-workspace', workspace); setActive(''); setMessages([]); setActivity([]); setBrowser(emptyBrowser); setPartial(''); setConfirmation(null); setRunning(false); setKnowledgeMode(localStorage.getItem(`orbit-knowledge-${workspace}`) || 'auto'); setKnowledgeDomains([]); void refresh().catch(e => setError(String(e))); void api<KnowledgeDomain[]>(`/api/knowledge/domains?workspace_id=${encodeURIComponent(workspace)}`).then(setKnowledgeDomains).catch(() => setKnowledgeDomains([])) }, [workspace, refresh])
  useEffect(() => { void refreshWorkspaces().catch(e => setError(String(e))); void api<Health>('/api/health').then(h => { setHealth(h); const available = (Object.keys(h.providers) as Provider[]).find(p => h.providers[p]); if (available) setProvider(current => h.providers[current] ? current : available) }).catch(() => setError('Cannot reach the backend. Start FastAPI on localhost:8000.')) }, [refreshWorkspaces])
  useEffect(() => {
    if (!active) return
    let disposed = false
    let retry: ReturnType<typeof setTimeout>
    setMessages([]); setActivity([]); setBrowser(emptyBrowser); setPartial(''); setConfirmation(null); setRunning(false); setConnected(false)
    function connect() {
      const ws = new WebSocket(`ws://localhost:8000/ws/${active}?workspace_id=${encodeURIComponent(workspace)}`)
      socket.current = ws
      ws.onopen = () => { if (!disposed) setConnected(true) }
      ws.onmessage = event => {
        if (disposed) return
        const data = JSON.parse(event.data)
        switch (data.type) {
          case 'state': setMessages(data.messages); setActivity(data.activity); setBrowser(data.browser); setPartial(data.partial); setRunning(data.status === 'running'); setConfirmation(data.confirmation); break
          case 'message': setMessages(prev => [...prev.filter(m => m.id !== data.message.id), data.message]); setPartial(''); void refresh(); break
          case 'delta': setPartial(prev => prev + data.text); break
          case 'activity': setActivity(prev => [...prev.filter(a => a.id !== data.id), data]); break
          case 'browser': setBrowser(data); break
          case 'status': setRunning(data.status === 'running'); if (data.status === 'running') { setActivity([]); setPartial('') } break
          case 'confirmation': setConfirmation(data); break
          case 'confirmation_cleared': setConfirmation(null); break
        }
      }
      ws.onclose = () => { if (!disposed) { setConnected(false); retry = setTimeout(connect, 1500) } }
    }
    connect()
    return () => { disposed = true; clearTimeout(retry); socket.current?.close() }
  }, [active, refresh, workspace])
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, partial, activity, confirmation])

  async function newChat() {
    try { const c = await api<Conversation>('/api/conversations', 'POST', { workspace_id: workspace }); await api('/api/sessions', 'POST', { conversation_id: c.id, workspace_id: workspace }); await refresh(); setActive(c.id); setError(''); return c.id } catch (e) { setError(String(e)); return '' }
  }
  async function createWorkspace() {
    const name = window.prompt('Workspace name')?.trim()
    if (!name) return
    try { const created = await api<Workspace>('/api/workspaces', 'POST', { name }); await refreshWorkspaces(); setWorkspace(created.id); setError('') } catch (e) { setError(String(e)) }
  }
  async function deleteWorkspace() {
    const selected = workspaces.find(item => item.id === workspace)
    if (!selected || selected.id === defaultWorkspace || running || deletingWorkspace) return
    const warning = 'Delete workspace ' + selected.name + '? This permanently deletes its conversations, skills, knowledge, workspace files, and generated downloads. This cannot be undone.'
    if (!window.confirm(warning)) return
    setDeletingWorkspace(true)
    try {
      await api('/api/workspaces/' + encodeURIComponent(selected.id), 'DELETE')
      localStorage.removeItem('orbit-provider-' + selected.id)
      setWorkspace(defaultWorkspace)
      await refreshWorkspaces()
      setError('')
    } catch (e) {
      setError(String(e))
    } finally {
      setDeletingWorkspace(false)
    }
  }
  async function send(override?: string) {
    const text = (override ?? input).trim()
    if (!text || running) return
    try {
      const id = active || await newChat()
      if (!id) return
      setInput(''); setError(''); setRunning(true)
      const explicitDomain = knowledgeDomains.some(domain => domain.id === knowledgeMode) ? knowledgeMode : null
      await api('/api/chat', 'POST', { session_id: id, workspace_id: workspace, message: text, provider, use_knowledge: knowledgeMode === 'off' ? false : knowledgeMode === 'auto' ? null : true, knowledge_domain_id: explicitDomain })
    } catch (e) { setError(String(e)); setRunning(false); setInput(text) }
  }
  async function remove(c: Conversation) {
    if (!window.confirm(`Delete â€œ${c.title}â€ and close its browser?`)) return
    try { await api(`/api/conversations/${c.id}?workspace_id=${encodeURIComponent(workspace)}`, 'DELETE'); if (active === c.id) { setActive(''); setMessages([]); setActivity([]); setBrowser(emptyBrowser); setPartial(''); setRunning(false) } await refresh() } catch(e) { setError(String(e)) }
  }
  async function rename(c: Conversation) {
    const title = window.prompt('Conversation name', c.title)
    if (!title?.trim()) return
    try { await api(`/api/conversations/${c.id}?workspace_id=${encodeURIComponent(workspace)}`, 'PATCH', { title }); await refresh() } catch(e) { setError(String(e)) }
  }
  function confirm(approved: boolean) { if (connected && confirmation) socket.current?.send(JSON.stringify({ type: 'confirm', id: confirmation.id, approved })) }
  const updateKnowledgeDomains = useCallback((domains: KnowledgeDomain[]) => {
    setKnowledgeDomains(domains)
    setKnowledgeMode(current => domains.some(domain => domain.id === current) || ['auto', 'off', 'all'].includes(current) ? current : 'auto')
  }, [])
  async function previewSource(source: KnowledgeSource) {
    try { setSourcePreview(await api<SourcePreview>(`/api/knowledge/sources/${source.chunk_id}?workspace_id=${encodeURIComponent(workspace)}`)) }
    catch (e) { setError(String(e)) }
  }
  const current = conversations.find(c => c.id === active)
  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={e => e.preventDefault()}><span className="brand-mark"><Orbit size={25} /></span> orbit<span className="local-tag">LOCAL</span></a>
      <div className="workspace-picker"><select aria-label="Active workspace" value={workspace} disabled={running || deletingWorkspace} onChange={e => setWorkspace(e.target.value)}>{workspaces.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><button title="Create workspace" aria-label="Create workspace" disabled={deletingWorkspace} onClick={() => void createWorkspace()}><Plus size={15}/></button><button className="workspace-delete" title={workspace === defaultWorkspace ? 'Default workspace cannot be deleted' : 'Delete workspace'} aria-label="Delete workspace" disabled={running || deletingWorkspace || workspace === defaultWorkspace} onClick={() => void deleteWorkspace()}><Trash2 size={14}/></button></div>
      <button className="new-chat" onClick={() => void newChat()}><Plus size={17} /> New conversation <span>+</span></button>
      <label className="search"><Search size={15}/><input aria-label="Search conversations" placeholder="Search conversations" value={search} onChange={e => setSearch(e.target.value)}/></label>
      <div className="section-label">YOUR WORKSPACE</div>
      <div className="workspace-tools"><button onClick={() => setSkillsOpen(true)}><BookOpen size={16}/><span>Skills</span><small>Reusable jobs</small></button><button onClick={() => setFilesOpen(true)}><FolderOpen size={16}/><span>Files</span><i className="dot green"/></button><button onClick={() => setKnowledgeOpen(true)}><BookMarked size={16}/><span>Knowledge</span><small>Azure RAG</small></button></div>
      <nav className="conversation-list">{conversations.filter(c => c.title.toLowerCase().includes(search.toLowerCase())).map(c => <div className={`conversation ${active === c.id ? 'selected' : ''}`} key={c.id}><button className="conversation-select" onClick={() => setActive(c.id)}><MessageSquare size={15}/><span>{c.title}</span></button><div className="conversation-actions"><button title="Rename conversation" onClick={() => void rename(c)}><Pencil size={12}/></button><button title="Delete conversation" onClick={() => void remove(c)}><Trash2 size={12}/></button></div></div>)}{!conversations.length && <p className="sidebar-empty">A little space for your next big idea.<br/>Your conversations will live here.</p>}</nav>
      <div className="sidebar-bottom"><div className="local-note"><ShieldCheck size={17}/><div><strong>Your browser. Your workspace.</strong><small>History stored on this computer</small></div></div><button className="settings-button" onClick={() => setSettingsOpen(true)}><Settings2 size={16}/> Settings <span className={`dot ${health ? 'green' : ''}`}/></button></div>
    </aside>
    <div className="workspace">
      <button className="theme-toggle" title={dark ? 'Switch to light mode' : 'Switch to dark mode'} onClick={() => setDark(!dark)}>{dark ? <Sun size={14}/> : <Moon size={14}/>}</button>
      <header><div className="breadcrumb">{workspaces.find(item => item.id === workspace)?.name || 'Workspace'} <span>/</span> <strong>{current?.title || 'New conversation'}</strong></div><div className="header-actions"><div className="model-picker"><span className="dot green"/><select aria-label="AI provider" value={provider} disabled={running} onChange={e => setProvider(e.target.value as Provider)}><option value="openai">OpenAI</option><option value="azure">Azure OpenAI</option><option value="anthropic">Claude</option></select><ChevronDown size={13}/></div><button className="icon-button" title="Toggle browser preview" onClick={() => setPreview(!preview)}><PanelRightClose size={18}/></button></div></header>
      <div className={`main-grid ${preview ? '' : 'no-preview'}`}>
        <main className="chat-pane">
          <div className="chat-scroll">
            {!messages.length && !running ? <div className="welcome"><div className="eyebrow"><span className="dot green"/> A BROWSER THAT WORKS WITH YOU</div><div className="welcome-orbit"><Orbit size={43} strokeWidth={1.3}/></div><h1>A little direction.<br/><span>A world of possibilities.</span></h1><p>Tell Orbit what you need. Your AI agent browses,<br className="desktop-break"/> explores, and gets things done â€” right here.</p><div className="suggestions">{prompts.map(([title, prompt], i) => <button key={title} onClick={() => setInput(prompt)}><span className="suggestion-icon">{i === 0 ? <Globe2 size={18}/> : i === 1 ? <Search size={18}/> : <Sparkles size={18}/>}</span><strong>{title}</strong><small>{prompt}</small><ArrowUpRight className="suggestion-arrow" size={16}/></button>)}</div><div className="welcome-foot"><ShieldCheck size={13}/> Real browser actions. You stay in control.</div></div> : <div className="message-list">{messages.map(m => <article className={`message ${m.role}`} key={m.id}><div className="message-avatar">{m.role === 'user' ? 'Y' : <Orbit size={18}/>}</div><div className="message-body"><div className="message-meta">{m.role === 'user' ? 'You' : 'Orbit'}<time>{new Date(m.created_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</time></div><div className="message-content">{m.content}</div>{m.sources && m.sources.length > 0 && <div className="message-sources"><strong>{m.retrieval?.source_count || m.sources.length} Sources</strong>{m.sources.map((source, index) => <button key={source.chunk_id} onClick={() => void previewSource(source)}><FileText size={13}/><span>{source.file_name || `Source ${index + 1}`}</span>{source.page_number != null && <small>p.{source.page_number}</small>}{source.section && source.page_number == null && <small>{source.section}</small>}</button>)}</div>}</div></article>)}<ActivityCard items={activity}/>{partial && <article className="message assistant"><div className="message-avatar"><Orbit size={18}/></div><div className="message-body"><div className="message-meta">Orbit <span className="typing-label">working</span></div><div className="message-content">{partial}<span className="caret"/></div></div></article>}{running && !partial && <div className="thinking"><span/><span/><span/> {confirmation ? 'Waiting for your approval' : 'Working in your browser'}</div>}{confirmation && <div className="confirmation"><ShieldCheck size={20}/><strong>Your confirmation is needed</strong><p>{confirmation.description}</p><div><button disabled={!connected} onClick={() => confirm(false)}>Cancel action</button><button disabled={!connected} className="primary" onClick={() => confirm(true)}>Confirm action</button></div></div>}<div ref={bottom}/></div>}
          </div>
          <div className="composer-wrap">{error && <div role="alert" className="error-banner">{error}<button title="Dismiss error" onClick={() => setError('')}><X size={14}/></button></div>}{health && !health.providers[provider] && <div className="setup-note"><span className="dot amber"/> Add your {provider === 'anthropic' ? 'Anthropic' : provider === 'azure' ? 'Azure OpenAI' : 'OpenAI'} API key in .env to get started.<button onClick={() => setSettingsOpen(true)}>Setup details <ArrowUpRight size={12}/></button></div>}<form className="composer" onSubmit={e => { e.preventDefault(); void send() }}><textarea aria-label="Message Orbit" placeholder="What would you like to do in the browser?" value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send() } }} rows={2}/><div className="composer-bottom"><label className="knowledge-select"><BookMarked size={14}/><select aria-label="Knowledge mode" value={knowledgeMode} disabled={running} onChange={e => setKnowledgeMode(e.target.value)}><option value="auto">Knowledge: Auto</option><option value="off">Knowledge: Off</option><option value="all">All workspace knowledge</option>{knowledgeDomains.map(domain => <option key={domain.id} value={domain.id}>{domain.name}</option>)}</select><ChevronDown size={12}/></label>{running ? <button type="button" className="stop-button" onClick={() => void api('/api/chat/stop', 'POST', { session_id: active, workspace_id: workspace }).catch(e => setError(String(e)))}><Square size={13} fill="currentColor"/> Stop</button> : <button className="send-button" disabled={!input.trim()} title="Send message"><ArrowUp size={19}/></button>}</div></form><div className="composer-caption"><span>Orbit can make mistakes. Review important actions.</span><span>â†µ to send Â· Shift â†µ for a new line</span></div></div>
        </main>
        {preview && <aside className="browser-pane"><div className="browser-heading"><div><Monitor size={17}/><strong>Browser preview</strong></div><span className={`connection-badge ${browser.status === 'connected' ? 'online' : ''}`}><span className="dot"/>{browser.status === 'connected' ? 'Live' : 'Standby'}</span></div><div className="browser-address"><Globe2 size={13}/><span>{browser.url || 'Your next destination awaits'}</span>{/^https?:/.test(browser.url) && <a href={browser.url} target="_blank" rel="noreferrer" title="Open page separately"><ExternalLink size={13}/></a>}</div><div className={`browser-viewport ${browser.screenshot ? 'has-image' : ''}`}>{browser.screenshot ? <ScreenshotPreview key={`${workspace}-${active}`} sessionId={active} workspaceId={workspace} version={browser.screenshot}/> : <div className="browser-empty"><div className="mini-window"><div><i/><i/><i/></div><Globe2 size={35} strokeWidth={1}/><span/><span/></div><h3>A window into your workflow</h3><p>When Orbit starts browsing, youâ€™ll see<br/>whatâ€™s happening here, as it happens.</p><span className="waiting-label"><span className="dot"/> Waiting for your first action</span></div>}</div><div className="browser-tabs"><div className="section-label">BROWSER TABS <span>{browser.tabs ? '' : '0'}</span></div>{browser.tabs ? <pre>{browser.tabs.replace(/###.*\n/g, '')}</pre> : <div className="empty-tabs"><Square size={14}/> No open tabs yet</div>}</div><div className="browser-info"><ShieldCheck size={16}/><p>Your browser stays open between tasks.<br/>Say <strong>â€œclose browserâ€</strong> when youâ€™re done.</p></div><div className="preview-footer"><span className={`dot ${connected ? 'green' : ''}`}/>{active ? connected ? 'Session connected' : 'Reconnecting to sessionâ€¦' : 'Local browser session'}<span>PLAYWRIGHT MCP</span></div></aside>}
      </div>
    </div>
    {skillsOpen && <SkillsPanel workspaceId={workspace} onClose={() => setSkillsOpen(false)} onRun={name => { setSkillsOpen(false); void send(`/run ${name}`) }}/>} 
    {filesOpen && <FilesPanel workspaceId={workspace} onClose={() => setFilesOpen(false)}/>}
    {knowledgeOpen && <KnowledgeCenter workspaceId={workspace} onClose={() => setKnowledgeOpen(false)} onDomainsChanged={updateKnowledgeDomains}/>}
    {sourcePreview && <div className="modal-backdrop" onClick={() => setSourcePreview(null)}><section className="source-modal" role="dialog" aria-modal="true" aria-label="Knowledge source" onClick={e => e.stopPropagation()}><button className="modal-close icon-button" title="Close source" onClick={() => setSourcePreview(null)}><X size={19}/></button><span className="eyebrow">RETRIEVED SOURCE</span><h2>{sourcePreview.source_file}</h2><div className="source-location">{sourcePreview.page_number != null && <span>Page {sourcePreview.page_number}</span>}{sourcePreview.section && <span>{sourcePreview.section}</span>}</div><pre>{sourcePreview.text}</pre></section></div>}
    {settingsOpen && <div className="modal-backdrop" onClick={() => setSettingsOpen(false)}><section className="settings-modal" role="dialog" aria-modal="true" aria-label="Settings" onClick={e => e.stopPropagation()}><button className="modal-close icon-button" title="Close settings" onClick={() => setSettingsOpen(false)}><X size={19}/></button><span className="eyebrow">LOCAL WORKSPACE</span><h2>Make Orbit yours.</h2><p>Set credentials and model names in <code>browser-agent/.env</code>, then restart the backend. Keys are never sent to this interface.</p>{(['openai','azure','anthropic'] as Provider[]).map(p => <div className="provider-row" key={p}><div><strong>{p === 'anthropic' ? 'Anthropic Claude' : p === 'azure' ? 'Azure OpenAI' : 'OpenAI'}</strong><small>{health?.models[p] || 'Model not configured'}</small></div><span className={health?.providers[p] ? 'ready' : 'not-ready'}>{health?.providers[p] ? 'Configured' : 'Needs API key'}</span></div>)}<div className="settings-summary"><span>Maximum steps <strong>{health?.max_steps || 50}</strong></span><span>Idle browser timeout <strong>{Math.round((health?.idle_timeout || 3600) / 60)} min</strong></span><span>MCP installation <strong>{health?.mcp || 'Checking'}</strong></span></div><p className="settings-fine">The app and history run locally. Prompts and page observations are sent to your selected AI provider. Enter passwords directly in the browser, never in chat.</p><button className="primary settings-done" onClick={() => setSettingsOpen(false)}>Back to workspace</button></section></div>}
  </div>
}





