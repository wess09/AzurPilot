import { useEffect, useState, type ReactNode } from 'react'
import { Download, Image, Terminal } from 'lucide-react'
import { api } from '../api/client'
import type { LogEntry, Logs as LogsData, Preview } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { Empty } from './ui'
import { LogPanel, LOG_LINE_RE, PURE_RULE_RE, RULE_RE } from './LogPanel'
import { SegmentedControl } from './SegmentedControl'

/** 截图视图顶部展示的日志条数，够看清当前进度即可，再多会挤掉画面。 */
export const RECENT_LOG_LINES = 3

interface CompactLine {id: number; level: string; time: string; text: string}

// 把一条渲染后的日志压成单行摘要。纯分割线没有信息量，返回 null 由调用方丢弃。
export function compactLine(entry: LogEntry): CompactLine | null {
  const raw = entry.text.replace(/[\r\n]+/g, ' ').trim()
  if (!raw || PURE_RULE_RE.test(raw)) return null
  const rule = RULE_RE.exec(raw)
  if (rule) return {id: entry.id, level: entry.level.toLowerCase(), time: '', text: rule[1]}
  const log = LOG_LINE_RE.exec(raw)
  if (log) return {id: entry.id, level: log[1].toLowerCase(), time: `${log[2] ? `${log[2]} ` : ''}${log[3]}`, text: log[4]}
  // Traceback 等原始行格式不固定，整体折成一行。
  return {id: entry.id, level: entry.level.toLowerCase(), time: '', text: raw}
}

// 按 id 合并增量，服务端重置游标时整体替换，最后只保留尾部若干条。
export function mergeLines(previous: CompactLine[], entries: LogEntry[], reset: boolean): CompactLine[] {
  const byId = new Map((reset ? [] : previous).map(line => [line.id, line]))
  entries.forEach(entry => {
    const line = compactLine(entry)
    if (line) byId.set(line.id, line)
  })
  return [...byId.values()].sort((a, b) => a.id - b.id).slice(-RECENT_LOG_LINES)
}

/**
 * 截图视图顶部的最近日志。
 *
 * 只读展示最后几条，不参与日志视图的搜索、级别筛选与清空，
 * 也不影响日志视图已滚到的位置。
 */
function RecentLogs({instance}: {instance: string}) {
  const [lines, setLines] = useState<CompactLine[]>([])
  const connection = useConnection()
  const {notify, ui} = useApp()
  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    setLines([])
    void api.request('logs.get', {instance}).then(value => {
      if (active) setLines(mergeLines([], value.entries, true))
    }).catch(error => notify(error.message, true))
    return () => { active = false }
  }, [connection, instance, notify])
  useEffect(() => api.onEvent(event => {
    if (event.topic !== 'logs') return
    const data = event.data as LogsData
    if (data.instance !== instance) return
    setLines(previous => mergeLines(previous, data.entries, data.reset))
  }), [instance])
  if (!lines.length) return null
  return <div className="preview-log" aria-label={ui('monitor.recentLogs')}>
    {lines.map(line => <div className="preview-log-line" key={line.id} title={line.text}>
      <span className={`log-lvl lvl-${line.level}`}>{line.level.toUpperCase()}</span>
      {line.time && <span className="preview-log-ts">{line.time}</span>}
      <span className="preview-log-msg">{line.text}</span>
    </div>)}
  </div>
}

/** actions：紧凑主题把实例设置按钮挂到工具栏右侧。 */
export function MonitorPanel({instance, actions}: {instance: string; actions?: ReactNode}) {
  const [view, setView] = useState('logs')
  const [frame, setFrame] = useState<Preview>()
  const {setPreviewEnabled, ui} = useApp()
  useEffect(() => {
    setPreviewEnabled(view === 'preview')
    return () => setPreviewEnabled(false)
  }, [view, setPreviewEnabled])
  useEffect(() => api.onEvent(event => {
    if (event.topic === 'preview' && (event.data as Preview).instance === instance) setFrame(event.data as Preview)
  }), [instance])
  return <section className="panel monitor-panel"><div className="monitor-tabs" aria-label={ui('monitor.title')}>
    <SegmentedControl label={ui('monitor.view')} value={view} onChange={setView} options={[
      {value: 'logs', label: <><Terminal size={15}/>{ui('monitor.logs')}</>},
      {value: 'preview', label: <><Image size={15}/>{ui('monitor.preview')}</>},
    ]}/>
    {actions}
    {view === 'preview' && frame?.image && <a className="text-button" href={frame.image} download={`${instance}-screenshot.jpg`}><Download size={14}/>{ui('monitor.saveScreenshot')}</a>}
  </div>
    <div className="monitor-view" hidden={view !== 'logs'}><LogPanel active={view === 'logs'}/></div>
    <div className="monitor-view" hidden={view !== 'preview'}>
      <RecentLogs instance={instance}/>
      <div className="preview-stage"><div className="preview-screen">{frame?.image ? <img src={frame.image} alt={ui('monitor.screenshotAlt')}/> : <Empty icon={<Image size={42}/>} title={ui('monitor.waitingScreenshot')}>{ui('monitor.screenshotHint')}</Empty>}</div></div>
    </div>
  </section>
}
