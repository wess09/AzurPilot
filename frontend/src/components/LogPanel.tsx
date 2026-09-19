import { Select } from './FormControls'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useParams } from 'react-router-dom'
import { Download, Pause, Play, Search, Terminal, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import type { Logs as LogsData, LogEntry } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { Empty } from '../components/ui'

export const LOG_LINE_RE = /^([A-Z]{4,8})\s+(?:(\d{4}-\d{2}-\d{2})\s+)?(\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)\s*│\s*([\s\S]*)$/
export const RULE_RE = /^[═─]{3,}\s*(.*?)\s*[═─]{3,}$/
export const PURE_RULE_RE = /^[═─]{3,}$/
export const CENTER_TITLE_RE = /^\s{3,}(.*?)\s{3,}$/

function highlightText(text: string, search: string): ReactNode {
  if (!text) return null
  const searchLower = search.trim().toLowerCase()

  // 词法正则：匹配高亮目标
  const tokenRegex = /(\b(?:True|False|None)\b)|(<<<[\s\S]*?>>>)|(\[[a-zA-Z0-9_.-]+\])|([\{\}\[\]\(\)])|((?:[a-zA-Z]:[/\\]|(?:\.{1,2}[/\\]|[/\\]))[\w.\-/\\]+)|(\b\d{2}:\d{2}:\d{2}(?:\.\d+)?\b)/g

  const nodes: ReactNode[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = tokenRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(renderSearchHighlights(text.slice(lastIndex, match.index), searchLower, `seg-${lastIndex}`))
    }
    const [full, boolVal, title, attrTag, brace, pathVal, timeVal] = match
    const key = `hl-${match.index}`

    if (boolVal) {
      const cls = boolVal === 'True' ? 'hl-bool-true' : boolVal === 'False' ? 'hl-bool-false' : 'hl-none'
      nodes.push(<span key={key} className={cls}>{renderSearchHighlights(full, searchLower, `${key}-s`)}</span>)
    } else if (title) {
      nodes.push(<span key={key} className="hl-title">{renderSearchHighlights(full, searchLower, `${key}-s`)}</span>)
    } else if (attrTag) {
      nodes.push(<span key={key} className="hl-attr">{renderSearchHighlights(full, searchLower, `${key}-s`)}</span>)
    } else if (brace) {
      nodes.push(<span key={key} className="hl-brace">{full}</span>)
    } else if (pathVal) {
      nodes.push(<span key={key} className="hl-path">{renderSearchHighlights(full, searchLower, `${key}-s`)}</span>)
    } else if (timeVal) {
      nodes.push(<span key={key} className="hl-time">{full}</span>)
    } else {
      nodes.push(renderSearchHighlights(full, searchLower, `${key}-s`))
    }
    lastIndex = match.index + full.length
  }

  if (lastIndex < text.length) {
    nodes.push(renderSearchHighlights(text.slice(lastIndex), searchLower, `seg-${lastIndex}`))
  }

  return <>{nodes}</>
}

function renderSearchHighlights(text: string, searchLower: string, keyPrefix: string): ReactNode {
  if (!text) return null
  if (!searchLower) return <span key={keyPrefix}>{text}</span>
  const lower = text.toLowerCase()
  const idx = lower.indexOf(searchLower)
  if (idx === -1) return <span key={keyPrefix}>{text}</span>

  const nodes: ReactNode[] = []
  let current = text
  let curLower = lower
  let k = 0

  while (true) {
    const matchIdx = curLower.indexOf(searchLower)
    if (matchIdx === -1) {
      if (current) nodes.push(<span key={`${keyPrefix}-t-${k}`}>{current}</span>)
      break
    }
    if (matchIdx > 0) {
      nodes.push(<span key={`${keyPrefix}-t-${k++}`}>{current.slice(0, matchIdx)}</span>)
    }
    nodes.push(<mark key={`${keyPrefix}-m-${k++}`} className="log-search-match">{current.slice(matchIdx, matchIdx + searchLower.length)}</mark>)
    current = current.slice(matchIdx + searchLower.length)
    curLower = curLower.slice(matchIdx + searchLower.length)
  }

  return <span key={keyPrefix}>{nodes}</span>
}

export function LogLine({entry, search, isCenter}: {entry: LogEntry; search: string; isCenter?: boolean}) {
  const rawText = entry.text.replace(/[\r\n]+$/, '')
  const trimmed = rawText.trim()

  // 1. 判断是否为纯分割线 (Pure Rule)
  const isPureRule = PURE_RULE_RE.test(trimmed)
  if (isPureRule) {
    const char = trimmed.includes('═') ? '═' : '─'
    return (
      <div className={`log-rule ${char === '═' ? 'rule-double' : 'rule-single'}`}>
        <span className="rule-bar" />
        <span className="rule-bar" />
      </div>
    )
  }

  // 2. 判断是否为带线标题 (Rule with title, 如 level 1/2)
  const ruleMatch = RULE_RE.exec(trimmed)
  if (ruleMatch && ruleMatch[1].trim()) {
    const title = ruleMatch[1].trim()
    const char = trimmed.includes('═') ? '═' : '─'
    return (
      <div className={`log-rule ${char === '═' ? 'rule-double' : 'rule-single'}`}>
        <span className="rule-bar" />
        <span className="rule-title">{highlightText(title, search)}</span>
        <span className="rule-bar" />
      </div>
    )
  }

  // 3. 判断是否为标准日志行
  const logMatch = LOG_LINE_RE.exec(rawText)
  if (logMatch) {
    const [, levelStr, dateStr, timeStr, messageStr] = logMatch
    const levelKey = levelStr.toLowerCase()
    return (
      <div className={`log-line log-entry-line level-${levelKey}`}>
        <span className={`log-lvl lvl-${levelKey}`}>{levelStr}</span>
        <span className="log-ts">{dateStr ? `${dateStr} ` : ''}{timeStr}</span>
        <span className="log-divider">│</span>
        <span className="log-msg">{highlightText(messageStr, search)}</span>
      </div>
    )
  }

  // 4. 判断是否为居中标题 (level 0 或其他居中文本)
  const isSingleLine = !rawText.includes('\n')
  const centerMatch = isSingleLine ? CENTER_TITLE_RE.exec(rawText) : null
  const shouldCenter = Boolean(
    isSingleLine && trimmed && (
      isCenter ||
      (centerMatch && centerMatch[1].trim())
    )
  )
  if (shouldCenter) {
    const title = trimmed
    return (
      <div className="log-line log-entry-line log-center-title">
        <span className="center-title-text">{highlightText(title, search)}</span>
      </div>
    )
  }

  // 5. 其他非标准行或多行 Traceback
  return (
    <div className={`log-line log-entry-line log-raw level-${entry.level.toLowerCase()}`}>
      <span className="log-msg">{highlightText(rawText, search)}</span>
    </div>
  )
}

const LOG_LEVELS = ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

function loadLogLevel(instance: string): string {
  try {
    const saved = localStorage.getItem(`azurpilot.log.level.${instance}`)
    if (saved && LOG_LEVELS.includes(saved)) return saved
  } catch { /* 存储不可用时使用默认等级。 */ }
  return 'ALL'
}

export function mergeLogEntries(previous: LogEntry[], incoming: LogEntry[], reset = false): LogEntry[] {
  if (reset) return incoming.slice(-400)
  const byId = new Map(previous.map(entry => [entry.id, entry]))
  incoming.forEach(entry => byId.set(entry.id, entry))
  return [...byId.values()].sort((a, b) => a.id - b.id).slice(-400)
}

export function LogPanel({active = true}: {active?: boolean}) {
  const {instance = ''} = useParams()
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [search, setSearch] = useState('')
  const [level, setLevel] = useState(() => loadLogLevel(instance))
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [follow, setFollow] = useState(true)
  const [floor, setFloor] = useState(0)
  const connection = useConnection()
  const {notify, ui} = useApp()
  const scroll = useRef<HTMLDivElement>(null)
  const pending = useRef<LogEntry[]>([])
  const raf = useRef(0)

  useEffect(() => setLevel(loadLogLevel(instance)), [instance])

  function updateLevel(next: string) {
    setLevel(next)
    try { localStorage.setItem(`azurpilot.log.level.${instance}`, next) } catch { /* 无存储权限时仅本页生效。 */ }
  }

  function cancelPending() {
    pending.current = []
    if (raf.current) cancelAnimationFrame(raf.current)
    raf.current = 0
  }

  function flushPending() {
    raf.current = 0
    const next = pending.current.shift()
    if (!next) return
    setEntries(previous => mergeLogEntries(previous, [next]))
    if (pending.current.length) raf.current = requestAnimationFrame(flushPending)
  }

  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    cancelPending()
    setFloor(0)
    setEntries([])
    void api.request('logs.get', {instance}).then(value => {
      if (active) setEntries(previous => mergeLogEntries(previous, value.entries))
    }).catch(error => notify(error.message, true))
    return () => { active = false }
  }, [connection, instance, notify])

  useEffect(() => {
    const stop = api.onEvent(event => {
      if (event.topic !== 'logs') return
      const data = event.data as LogsData
      if (data.instance !== instance) return
      setFloor(previous => data.cursor < previous ? 0 : previous)
      if (data.reset || data.entries.length > 8) {
        cancelPending()
        setEntries(previous => mergeLogEntries(previous, data.entries, data.reset))
        return
      }
      pending.current.push(...data.entries)
      if (!raf.current) raf.current = requestAnimationFrame(flushPending)
    })
    return () => {
      stop()
      cancelPending()
    }
  }, [instance])

  useEffect(() => {
    if (active && follow && scroll.current) {
      scroll.current.scrollTop = scroll.current.scrollHeight
    }
  }, [entries, follow, active])

  const visible = entries.filter(entry =>
    entry.id > floor &&
    (level === 'ALL' || entry.level === level) &&
    entry.text.toLowerCase().includes(search.toLowerCase())
  )

  function download() {
    const url = URL.createObjectURL(new Blob([visible.map(entry => entry.text).join('\n')], {type: 'text/plain;charset=utf-8'}))
    const link = document.createElement('a')
    link.href = url
    link.download = `${instance}-logs.txt`
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <section className="log-panel">
      <div className="log-toolbar" aria-label={ui('log.tools')}>
        <button className={`icon-button ${search || level !== 'ALL' ? 'filter-active' : ''}`} aria-label={filtersOpen ? ui('log.filtersCollapse') : ui('log.filtersExpand')} title={ui('log.searchAndFilter')} aria-expanded={filtersOpen} aria-controls="log-filters" onClick={() => setFiltersOpen(!filtersOpen)}><Search size={15}/></button>
        <button className="icon-button" onClick={() => setFollow(!follow)} aria-label={follow ? ui('log.pauseFollow') : ui('log.resumeFollow')}>
          {follow ? <Pause size={15} /> : <Play size={15} />}
        </button>
        <button className="icon-button" onClick={() => setFloor(entries.at(-1)?.id ?? 0)} aria-label={ui('log.clearView')}>
          <Trash2 size={15} />
        </button>
        <button className="text-button" onClick={download} aria-label={ui('log.export')}>
          <Download size={15} />{ui('log.exportShort')}
        </button>
      </div>
      {filtersOpen && <div className="log-filters" id="log-filters">
        <div className="input-icon">
          <Search size={15} />
          <input aria-label={ui('log.search')} placeholder={ui('log.searchPlaceholder')} value={search} onChange={event => setSearch(event.target.value)} />
        </div>
        <Select aria-label={ui('log.level')} value={level} onChange={event => updateLevel(event.target.value)}>
          {LOG_LEVELS.map(item => (
            <option key={item} value={item}>{item === 'ALL' ? ui('log.allLevels') : item}</option>
          ))}
        </Select>
        <span>{ui('log.recent', {count: entries.length})}</span>
      </div>}
      <div className="log-content" ref={scroll} aria-label={ui('log.content')}>
        {visible.length ? (
          visible.map((entry, index) => {
            const prev = visible[index - 1]
            const next = visible[index + 1]
            const isCenterByContext = Boolean(
              prev && next &&
              PURE_RULE_RE.test(prev.text.trim()) && prev.text.includes('═') &&
              PURE_RULE_RE.test(next.text.trim()) && next.text.includes('═') &&
              !PURE_RULE_RE.test(entry.text.trim()) &&
              !LOG_LINE_RE.test(entry.text.trim())
            )
            return (
              <LogLine
                key={entry.id}
                entry={entry}
                search={search}
                isCenter={isCenterByContext}
              />
            )
          })
        ) : (
          <Empty icon={<Terminal size={26} />} title={entries.length ? ui('log.noMatch') : ui('log.ready')}>
            {entries.length ? ui('log.adjustFilter') : ui('log.waiting')}
          </Empty>
        )}
      </div>
    </section>
  )
}
