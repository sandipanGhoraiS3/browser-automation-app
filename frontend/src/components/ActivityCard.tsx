import { Check, LoaderCircle, X, MousePointer2, FolderOpen, BookOpen } from 'lucide-react'
import type { Activity } from '../types'
export function ActivityCard({ items }: { items: Activity[] }) {
  if (!items.length) return null
  return <section className="activity"><div className="activity-heading"><MousePointer2 size={14} /> Agent activity <span>{items.length} actions</span></div>{items.map(item => <details key={item.id}><summary><span className={`action-icon ${item.status}`}>{item.status === 'running' ? <LoaderCircle size={14} className="spin" /> : item.status === 'success' ? <Check size={14} /> : <X size={14} />}</span><div><strong><span className={`category-label ${item.category || "browser"}`}>{item.category === "file" ? <FolderOpen size={11}/> : item.category === "skill" ? <BookOpen size={11}/> : <MousePointer2 size={11}/>} {item.category || "browser"}</span>{item.name}</strong><small>{item.description}</small></div><span className="duration">{item.duration !== undefined ? `${item.duration}s` : item.status}</span></summary><p>{item.details || 'Waiting for the browser…'}</p></details>)}</section>
}
