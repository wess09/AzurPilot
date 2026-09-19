import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react'
import { AlertCircle, LoaderCircle, X } from 'lucide-react'
import { GlassMaterial } from './GlassMaterial'
import type { Status } from '../api/types'
import { useApp } from '../app/context'

export function StatusBadge({status}: {status: Status}) {
  const {ui} = useApp()
  return <span className={`status ${status}`}><i />{{running: ui('status.running'), stopped: ui('status.stopped'), error: ui('status.error'), updating: ui('status.updating')}[status]}</span>
}
export function Empty({icon, title, children}: {icon?: ReactNode; title: string; children?: ReactNode}) {
  return <div className="empty">{icon}<strong>{title}</strong><div>{children}</div></div>
}
export function Loading() {
  const {ui} = useApp()
  return <div className="loading" role="status"><LoaderCircle className="spin" size={22} />{ui('common.loading')}</div>
}
export function ErrorBox({message, retry}: {message: string; retry?: () => void}) {
  const {ui} = useApp()
  return <div role="alert" className="error-box"><AlertCircle size={18}/><span>{message}</span>{retry && <button onClick={retry}>{ui('common.retry')}</button>}</div>
}
export function Modal({title, children, onClose, className = ''}: {title: string; children: ReactNode; onClose: () => void; className?: string}) {
  const ref = useRef<HTMLDialogElement>(null)
  const {ui} = useApp()
  useEffect(() => { ref.current?.showModal(); return () => ref.current?.close() }, [])
  return <dialog ref={ref} onCancel={onClose} className={`modal ${className}`.trim()}>
    <div className="panel-heading"><h2>{title}</h2><button className="icon-button" aria-label={ui('common.close')} onClick={onClose}><X size={20}/></button></div>
    {children}
  </dialog>
}

/** 用文字轮廓裁切背景滤镜，避免模糊扩散到标题外的矩形区域。 */
function createTitleMask(title: string) {
  const escaped = title.replace(/[&<>]/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[character]!))
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 100" preserveAspectRatio="none"><text x="0" y="82" textLength="1000" lengthAdjust="spacingAndGlyphs" fill="white" stroke="white" stroke-width="4" paint-order="stroke" font-family="-apple-system,BlinkMacSystemFont,SF Pro Text,Segoe UI,PingFang SC,Microsoft YaHei,sans-serif" font-size="84" font-weight="700">${escaped}</text></svg>`
  return `url("data:image/svg+xml,${encodeURIComponent(svg)}")`
}

export function PageTitle({title, actions, className = ''}: {title: string; actions?: ReactNode; className?: string}) {
  const {theme} = useApp()
  const titleStyle = theme === 'minimal' || theme === 'extreme' ? undefined : {'--page-title-mask': createTitleMask(title)} as CSSProperties
  return <div className={`page-title ${className}`.trim()}><h1 aria-label={title} data-text={title} style={titleStyle}>{title}</h1>{actions && <div className="title-actions"><GlassMaterial/>{actions}</div>}</div>
}
