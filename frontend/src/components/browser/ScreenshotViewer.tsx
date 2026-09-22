import { useCallback, useEffect, useRef, useState } from 'react'
import { Maximize2, Minus, Plus, Scan, X } from 'lucide-react'
interface Props { src: string; expanded?: boolean; onExpand?: () => void; onClose?: () => void }
export function ScreenshotViewer({ src, expanded = false, onExpand, onClose }: Props) {
  const surface = useRef<HTMLDivElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const [size, setSize] = useState({ width: 1280, height: 800 })
  const [zoom, setZoom] = useState(1)
  const [fit, setFit] = useState(true)
  const [viewport, setViewport] = useState({ width: 400, height: 300 })
  const [dragging, setDragging] = useState(false)
  const drag = useRef<{ x: number; y: number; left: number; top: number; moved: boolean } | null>(null)
  const scale = Math.max(.02, fit ? Math.min(1, (viewport.width - 16) / size.width, expanded ? (viewport.height - 16) / size.height : 1) : zoom)
  const changeZoom = useCallback((next: number) => {
    const c = surface.current, target = Math.max(.05, Math.min(3, next))
    const x = c ? (c.scrollLeft + c.clientWidth / 2) / scale : 0, y = c ? (c.scrollTop + c.clientHeight / 2) / scale : 0
    setFit(false); setZoom(target)
    requestAnimationFrame(() => { if (c) { c.scrollLeft = x * target - c.clientWidth / 2; c.scrollTop = y * target - c.clientHeight / 2 } })
  }, [scale])
  useEffect(() => {
    const c = surface.current
    if (!c) return
    const observer = new ResizeObserver(([entry]) => setViewport({ width: entry.contentRect.width, height: entry.contentRect.height }))
    observer.observe(c)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    if (!expanded) return
    const previous = document.activeElement as HTMLElement | null, overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'; closeButton.current?.focus()
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose?.()
      if (event.key === 'Tab') {
        const items = surface.current?.parentElement?.querySelectorAll<HTMLElement>('button, [tabindex="0"]')
        if (!items?.length) return
        if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items[items.length - 1].focus() }
        else if (!event.shiftKey && document.activeElement === items[items.length - 1]) { event.preventDefault(); items[0].focus() }
      }
    }
    document.addEventListener('keydown', keydown)
    return () => { document.body.style.overflow = overflow; document.removeEventListener('keydown', keydown); previous?.focus() }
  }, [expanded, onClose])
  useEffect(() => {
    const c = surface.current
    if (!c || !expanded) return
    const wheel = (event: WheelEvent) => { event.preventDefault(); changeZoom(scale * (event.deltaY < 0 ? 1.15 : 1 / 1.15)) }
    c.addEventListener('wheel', wheel, { passive: false })
    return () => c.removeEventListener('wheel', wheel)
  }, [expanded, scale, changeZoom])
  return <div className={`image-viewer ${expanded ? 'expanded' : ''}`} role={expanded ? 'dialog' : undefined} aria-modal={expanded || undefined} aria-label={expanded ? 'Screenshot viewer' : 'Screenshot preview'}>
    <div className="screenshot-toolbar"><span>{expanded ? 'Screenshot viewer' : 'Screenshot'}</span><button title="Fit image" aria-label="Fit image" className={fit ? 'active' : ''} onClick={() => { setFit(true); if (surface.current) { surface.current.scrollTop = 0; surface.current.scrollLeft = 0 } }}><Scan size={14}/></button><button aria-label="Zoom out" onClick={() => changeZoom(scale / 1.25)} disabled={scale <= .05}><Minus size={14}/></button><button className="zoom-value" title="Reset zoom to 100%" aria-label="Reset zoom to 100%" onClick={() => changeZoom(1)}>{Math.round(scale * 100)}%</button><button aria-label="Zoom in" onClick={() => changeZoom(scale * 1.25)} disabled={scale >= 3}><Plus size={14}/></button>{expanded ? <button ref={closeButton} aria-label="Close viewer" onClick={onClose}><X size={18}/></button> : <button aria-label="Enlarge screenshot" onClick={onExpand}><Maximize2 size={14}/></button>}</div>
    <div ref={surface} className={`image-surface ${dragging ? 'dragging' : ''}`} tabIndex={0} aria-label="Screenshot canvas" onKeyDown={e => { if (!expanded && e.key === 'Enter') onExpand?.() }} onPointerDown={e => { if (e.button !== 0) return; drag.current = { x: e.clientX, y: e.clientY, left: e.currentTarget.scrollLeft, top: e.currentTarget.scrollTop, moved: false }; e.currentTarget.setPointerCapture(e.pointerId); setDragging(true) }} onPointerMove={e => { if (!drag.current) return; const dx = e.clientX - drag.current.x, dy = e.clientY - drag.current.y; if (Math.abs(dx) + Math.abs(dy) > 4) drag.current.moved = true; e.currentTarget.scrollLeft = drag.current.left - dx; e.currentTarget.scrollTop = drag.current.top - dy }} onPointerUp={() => { const moved = drag.current?.moved; drag.current = null; setDragging(false); if (!expanded && !moved) onExpand?.() }} onPointerCancel={() => { drag.current = null; setDragging(false) }} onDoubleClick={() => { if (fit) changeZoom(1); else setFit(true) }}>
      <div className="image-size" style={{ width: Math.max(viewport.width - 2, size.width * scale + 16), height: Math.max(viewport.height - 2, size.height * scale + 16) }}><img src={src} alt="Latest real browser screenshot" draggable={false} onLoad={e => setSize({ width: e.currentTarget.naturalWidth, height: e.currentTarget.naturalHeight })} style={{ width: size.width * scale, height: size.height * scale }}/></div>
    </div>{expanded && <div className="viewer-help">Scroll to zoom · Drag to pan · Double-click for fit / 100% · Esc to close</div>}
  </div>
}
