import { useCallback, useEffect, useState } from 'react'
import { BookOpen, Plus, Play, Pencil, Trash2, X, ArrowLeft, Save, FolderOpen } from 'lucide-react'
import { api } from '../lib/api'
import type { Skill } from '../types'

const initialInstructions = `## Preconditions
Describe required website, sign-in, and inputs. Ask for anything missing.

## Steps
1. Inspect the current page.
2. Find the relevant information by its visible labels.
3. Save the result inside the allowed file workspace.

## Output
Return findings and saved file paths.

## Browser Rules
Use fresh snapshots and semantic actions. Keep the browser open.

## Recovery
Inspect current state after a failure. Never invent missing data or reuse stale references.`

export function SkillsPanel({ workspaceId, onClose, onRun }: { workspaceId: string; onClose: () => void; onRun: (name: string) => void }) {
  const [skills, setSkills] = useState<Skill[]>([])
  const [issues, setIssues] = useState<{ name: string; error: string }[]>([])
  const [selected, setSelected] = useState<Skill | null>(null)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState(false)
  const [markdown, setMarkdown] = useState('')
  const [name, setName] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [description, setDescription] = useState('')
  const [instructions, setInstructions] = useState(initialInstructions)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const refresh = useCallback(async () => { const result = await api<{ skills: Skill[]; errors: typeof issues }>(`/api/skills?workspace_id=${encodeURIComponent(workspaceId)}`); setSkills(result.skills); setIssues(result.errors) }, [workspaceId])
  useEffect(() => { void refresh().catch(e => setError(String(e))) }, [refresh])
  useEffect(() => { const key = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }; document.addEventListener('keydown', key); return () => document.removeEventListener('keydown', key) }, [onClose])
  async function save() {
    setBusy(true); setError('')
    try {
      const saved = creating ? await api<Skill>(`/api/skills?workspace_id=${encodeURIComponent(workspaceId)}`, 'POST', { metadata: { name, display_name: displayName, description, version: '1.0', category: 'workflow', requires_browser: true, requires_files: true }, instructions }) : await api<Skill>(`/api/skills/${selected!.metadata.name}?workspace_id=${encodeURIComponent(workspaceId)}`, 'PUT', { markdown, revision: selected!.revision })
      await refresh(); setSelected(saved); setEditing(false); setCreating(false)
    } catch(e) { setError(String(e)) } finally { setBusy(false) }
  }
  async function remove(skill: Skill) {
    if (!window.confirm(`Delete skill â€œ${skill.metadata.display_name}â€?`)) return
    try { await api(`/api/skills/${skill.metadata.name}?workspace_id=${encodeURIComponent(workspaceId)}`, 'DELETE'); setSelected(null); await refresh() } catch(e) { setError(String(e)) }
  }
  return <div className="modal-backdrop"><section className="skills-modal" role="dialog" aria-modal="true" aria-label="Skill library"><div className="library-header"><div><span className="eyebrow">REUSABLE WORKFLOWS</span><h2><BookOpen size={23}/> Skill library</h2></div><button className="icon-button" aria-label="Close skills" onClick={onClose}><X size={20}/></button></div><p className="library-intro">Turn a good workflow into a daily habit. Skills guide your agent with reusable, human-readable instructions.</p>{error && <div className="error-banner" role="alert">{error}</div>}
    {selected || creating ? <div className="skill-detail"><button className="text-button" onClick={() => { setSelected(null); setCreating(false); setEditing(false); setError('') }}><ArrowLeft size={14}/> All skills</button>{creating ? <><div className="skill-fields"><label>Skill ID<input aria-label="Skill ID" value={name} onChange={e => setName(e.target.value)} placeholder="daily_report" pattern="[a-z][a-z0-9_]*"/></label><label>Display name<input aria-label="Display name" value={displayName} onChange={e => setDisplayName(e.target.value)} placeholder="Daily Report"/></label></div><label className="field-label">Description<input aria-label="Skill description" value={description} onChange={e => setDescription(e.target.value)}/></label><label className="field-label">Workflow Â· Markdown<textarea aria-label="Skill instructions" className="skill-editor" value={instructions} onChange={e => setInstructions(e.target.value)}/></label></> : <><div className="detail-title"><div><h3>{selected!.metadata.display_name}</h3><span>{selected!.metadata.category} Â· v{selected!.metadata.version}</span></div><div className="skill-actions"><button title="Edit skill" onClick={() => { setEditing(true); setMarkdown(selected!.markdown) }}><Pencil size={15}/></button><button title="Delete skill" onClick={() => void remove(selected!)}><Trash2 size={15}/></button></div></div>{editing ? <textarea aria-label="Edit skill Markdown" className="skill-editor" value={markdown} onChange={e => setMarkdown(e.target.value)}/> : <pre className="skill-document">{selected!.markdown}</pre>}</>}
    <div className="library-footer">{creating || editing ? <button disabled={busy} className="primary" onClick={() => void save()}><Save size={14}/> {busy ? 'Savingâ€¦' : 'Save skill'}</button> : <button className="primary" onClick={() => onRun(selected!.metadata.name)}><Play size={14}/> Run skill</button>}</div></div> : <><div className="library-tools"><span>{skills.length} skills in your workspace</span><button className="primary" onClick={() => { setCreating(true); setName(''); setDisplayName(''); setDescription(''); setInstructions(initialInstructions) }}><Plus size={14}/> Create skill</button></div><div className="skill-grid">{skills.map(skill => <article className="skill-tile" key={skill.metadata.name}><div className="skill-tile-top"><BookOpen size={19}/><span>{skill.metadata.category}</span></div><button className="skill-title" onClick={() => setSelected(skill)}>{skill.metadata.display_name}</button><p>{skill.metadata.description}</p><div className="skill-capabilities">{skill.metadata.requires_browser && <span>Browser</span>}{skill.metadata.requires_files && <span>Files</span>}</div><div className="skill-tile-bottom"><button onClick={() => setSelected(skill)}>View / Edit</button><button onClick={() => onRun(skill.metadata.name)}><Play size={12}/> Run</button></div></article>)}</div>{issues.map(issue => <div className="error-banner" key={issue.name}>Invalid skill â€œ{issue.name}â€: {issue.error}</div>)}<div className="library-tip"><FolderOpen size={15}/><span>Saved as local Markdown files. Ask Orbit: â€œSave this workflow as a skill.â€</span></div></>}
    </section></div>
}


