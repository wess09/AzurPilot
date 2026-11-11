/**
 * @fileoverview 实例实时控制台日志面板组件。
 */

import { Select } from './FormControls'
import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { ArrowDownUp, Download, LayoutGrid, Pause, Play, Search, Terminal, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import type { Logs as LogsData, LogEntry } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { Empty } from '../components/ui'
import { Input } from './ui/input'
import { LogCardView, findVisibleRange, renderTokens, safeRaf, safeCancelRaf, OVERSCAN_BUFFER_PX } from './LogCardView'

export const LOG_LINE_RE = /^([A-Z]{4,8})\s+(?:(\d{4}-\d{2}-\d{2})\s+)?(\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)\s*│\s*([\s\S]*)$/
export const RULE_RE = /^[═─]{3,}\s*(.*?)\s*[═─]{3,}$/
export const PURE_RULE_RE = /^[═─]{3,}$/
export const CENTER_TITLE_RE = /^\s{3,}(.*?)\s{3,}$/
export const LOG_ENTRY_LIMIT = 1000
const VIRTUAL_LINE_THRESHOLD = 120
/* 未实测到高度的日志行先按这个值占位，实测后替换。 */
export const LINE_HEIGHT_ESTIMATE = 18

/** 日志跟随的每帧步长上限（像素）；距离更近时按距离收比例。 */
export const MAX_FOLLOW_STEP = 24

export interface LogBufferState {
  entries: LogEntry[]
  reset: boolean
  cursor: number | null
}

/**
 * 将高频推送的流式日志加入微批缓冲队列
 * 若收到 reset 信号，则清除前置缓冲并标记 reset，后序同一批次的 entries 连续追加
 */
export function queueLogEvent(
  buffer: LogBufferState,
  data: { entries: LogEntry[]; reset?: boolean; cursor: number }
): void {
  if (data.reset) {
    buffer.reset = true
    buffer.entries = [...data.entries]
  } else {
    buffer.entries.push(...data.entries)
  }
  buffer.cursor = data.cursor
}

/** 跟随步长：远时按上限匀速，近时按距离收比例，新日志逐帧滚入而不跳到末尾。 */
export function followStep(remaining: number, maxStep = MAX_FOLLOW_STEP) {
  return Math.sign(remaining) * Math.min(maxStep, Math.max(1, Math.abs(remaining) * .35))
}

/** 逐行高度表：已实测的行用实测值，其余用实测均高占位（无实测时用估值），并给出每行的偏移与总高。 */
export function buildLineLayout(entries: LogEntry[], measured: Map<number, number>, fallback: number) {
  let sum = 0
  let count = 0
  for (const height of measured.values()) {
    sum += height
    count += 1
  }
  const estimate = count ? sum / count : fallback
  const heights = new Array<number>(entries.length)
  const offsets = new Array<number>(entries.length)
  let total = 0
  for (let index = 0; index < entries.length; index++) {
    const height = measured.get(entries[index].id) ?? estimate
    heights[index] = height
    offsets[index] = total
    total += height
  }
  return {heights, offsets, total}
}

/**
 * 所有日志入口先在纯数据层截断，避免异常历史 payload 进入 React state 后创建数万 DOM。
 * 正常后端只保留约 400 条；这里的 1000 条是客户端独立的防御上限。
 */
export function mergeLogEntries(previous: LogEntry[], incoming: LogEntry[], reset = false): LogEntry[] {
  const recent = incoming.length > LOG_ENTRY_LIMIT ? incoming.slice(-LOG_ENTRY_LIMIT) : incoming
  const entries = new Map<number, LogEntry>()
  if (!reset) for (const entry of previous.slice(-LOG_ENTRY_LIMIT)) entries.set(entry.id, entry)
  for (const entry of recent) entries.set(entry.id, entry)
  return [...entries.values()].sort((a, b) => a.id - b.id).slice(-LOG_ENTRY_LIMIT)
}

export const LogLine = memo(function LogLine({entry, search, isCenter, fresh}: {entry: LogEntry; search: string; isCenter?: boolean; fresh?: boolean}) {
  const rawText = entry.text.replace(/[\r\n]+$/, '')
  const trimmed = rawText.trim()
  const freshClass = fresh ? ' motion-enter' : ''

  // 1. 判断是否为纯分割线 (Pure Rule)
  const isPureRule = PURE_RULE_RE.test(trimmed)
  if (isPureRule) {
    const char = trimmed.includes('═') ? '═' : '─'
    return (
      <div className={`log-rule ${char === '═' ? 'rule-double' : 'rule-single'}${freshClass}`} data-line-id={entry.id}>
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
      <div className={`log-rule ${char === '═' ? 'rule-double' : 'rule-single'}${freshClass}`} data-line-id={entry.id}>
        <span className="rule-bar" />
        <span className="rule-title">{renderTokens(title, search)}</span>
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
      <div className={`log-line log-entry-line level-${levelKey}${freshClass}`} data-line-id={entry.id}>
        <span className={`log-lvl lvl-${levelKey}`}>{levelStr}</span>
        <span className="log-ts">{dateStr ? `${dateStr} ` : ''}{timeStr}</span>
        <span className="log-divider">│</span>
        <span className="log-msg">{renderTokens(messageStr, search)}</span>
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
      <div className={`log-line log-entry-line log-center-title${freshClass}`} data-line-id={entry.id}>
        <span className="center-title-text">{renderTokens(title, search)}</span>
      </div>
    )
  }

  // 5. 其他非标准行或多行 Traceback
  return (
    <div className={`log-line log-entry-line log-raw level-${entry.level.toLowerCase()}${freshClass}`} data-line-id={entry.id}>
      <span className="log-msg">{renderTokens(rawText, search)}</span>
    </div>
  )
})

const LOG_LEVELS = ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

function loadLogLevel(instance: string): string {
  try {
    const saved = localStorage.getItem(`azurpilot.log.level.${instance}`)
    if (saved && LOG_LEVELS.includes(saved)) return saved
  } catch { /* 存储不可用时使用默认等级。 */ }
  return 'ALL'
}

/** 日志排序：默认正序（旧→新），与自动滚到底的行为配套。 */
function loadLogDescending(instance: string): boolean {
  try { return localStorage.getItem(`azurpilot.log.order.${instance}`) === 'desc' } catch { return false }
}

function loadLogViewMode(): 'cards' | 'classic' {
  try {
    const saved = localStorage.getItem('azurpilot.log.viewMode')
    if (saved === 'cards' || saved === 'classic') return saved
  } catch { /* 存储不可用时默认卡片视图 */ }
  return 'cards'
}

export function LogPanel({active = true, logs}: {active?: boolean; logs?: LogsData | null}) {
  const {instance = ''} = useParams()
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [search, setSearch] = useState('')
  const [level, setLevel] = useState(() => loadLogLevel(instance))
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [follow, setFollow] = useState(true)
  const [descending, setDescending] = useState(() => loadLogDescending(instance))
  const [viewMode, setViewMode] = useState<'cards' | 'classic'>(() => loadLogViewMode())
  const [floor, setFloor] = useState(0)
  const connection = useConnection()
  const external = logs !== undefined
  const {notify, ui} = useApp()
  const scroll = useRef<HTMLDivElement>(null)
  /* 已渲染到的最大日志 id：大于它的增量行做入场动画（初始加载不播）。 */
  const freshFrom = useRef<number | null>(null)

  /** 流式日志微批处理缓冲队列，防止高频 WebSocket 推送造成密集 React 重绘 */
  const logBuffer = useRef<LogBufferState & { rafId: number | null }>({
    entries: [],
    reset: false,
    cursor: null,
    rafId: null,
  })

  const flushBuffer = useRef(() => {})
  flushBuffer.current = () => {
    const buf = logBuffer.current
    if (buf.rafId !== null) {
      safeCancelRaf(buf.rafId)
      buf.rafId = null
    }
    const { entries: bufEntries, reset: bufReset, cursor: bufCursor } = buf
    if (bufEntries.length === 0 && !bufReset && bufCursor === null) return

    buf.entries = []
    buf.reset = false
    buf.cursor = null

    if (bufCursor !== null) {
      setFloor(previous => bufCursor < previous ? 0 : previous)
    }
    if (bufEntries.length > 0 || bufReset) {
      setEntries(previous => mergeLogEntries(previous, bufEntries, bufReset))
    }
  }

  useEffect(() => {
    setLevel(loadLogLevel(instance))
    setDescending(loadLogDescending(instance))
  }, [instance])

  function updateLevel(next: string) {
    setLevel(next)
    try { localStorage.setItem(`azurpilot.log.level.${instance}`, next) } catch { /* 无存储权限时仅本页生效。 */ }
  }

  function toggleViewMode() {
    setViewMode(prev => {
      const next = prev === 'cards' ? 'classic' : 'cards'
      try { localStorage.setItem('azurpilot.log.viewMode', next) } catch { /* 同上 */ }
      return next
    })
  }

  function toggleOrder() {
    setDescending(previous => {
      const next = !previous
      try { localStorage.setItem(`azurpilot.log.order.${instance}`, next ? 'desc' : 'asc') } catch { /* 同上。 */ }
      return next
    })
  }

  useEffect(() => {
    if (connection !== 'ready' || external) return
    let active = true
    const buf = logBuffer.current
    if (buf.rafId !== null) {
      safeCancelRaf(buf.rafId)
      buf.rafId = null
    }
    buf.entries = []
    buf.reset = false
    buf.cursor = null

    setFloor(0)
    setEntries([])
    void api.request('logs.get', {instance}).then(value => {
      if (active) setEntries(previous => mergeLogEntries(previous, value.entries))
    }).catch(error => notify(error.message, true))
    return () => {
      active = false
      if (buf.rafId !== null) {
        safeCancelRaf(buf.rafId)
        buf.rafId = null
      }
      buf.entries = []
      buf.reset = false
      buf.cursor = null
    }
  }, [connection, instance, notify, external])

  useEffect(() => {
    if (!logs || logs.instance !== instance) return
    queueLogEvent(logBuffer.current, logs)
    flushBuffer.current()
  }, [logs, instance])

  useEffect(() => {
    if (external) return
    const unsubscribe = api.onEvent(event => {
      if (event.topic !== 'logs') return
      const data = event.data as LogsData
      if (data.instance !== instance) return

      const buf = logBuffer.current
      queueLogEvent(buf, data)

      if (buf.rafId === null) {
        buf.rafId = safeRaf(() => {
          buf.rafId = null
          flushBuffer.current()
        })
      }
    })

    return () => {
      unsubscribe()
      const buf = logBuffer.current
      if (buf.rafId !== null) {
        safeCancelRaf(buf.rafId)
        buf.rafId = null
      }
      buf.entries = []
      buf.reset = false
      buf.cursor = null
    }
  }, [instance, external])

  useLayoutEffect(() => {
    freshFrom.current = entries.at(-1)?.id ?? null
  }, [entries])

  useLayoutEffect(() => {
    if (!active || !follow || !scroll.current) return
    const container = scroll.current
    /* 量与写都放进 rAF：layout effect 阶段刚改完 DOM，此刻读 scrollHeight 会强制同步布局；
       每帧只在帧首读一次 scrollTop、帧尾写一次。
       只改日志容器自身的滚动位置，不会像尾部元素的 scrollIntoView 那样连带滚动整个页面。 */
    let frame = requestAnimationFrame(function step() {
      const top = container.scrollTop
      const target = descending ? 0 : container.scrollHeight - container.clientHeight
      const remaining = target - top
      /* 与目标相距超过一屏：直接落位，不做逐帧滚入。 */
      if (Math.abs(remaining) > container.clientHeight) {container.scrollTop = target; return}
      if (Math.abs(remaining) <= 1) {if (remaining !== 0) container.scrollTop = target; return}
      container.scrollTop = top + followStep(remaining)
      frame = requestAnimationFrame(step)
    })
    return () => cancelAnimationFrame(frame)
  }, [entries, follow, active, descending])

  const searchLower = search.trim().toLowerCase()
  const visible = entries.filter(entry =>
    entry.id > floor &&
    (level === 'ALL' || entry.level === level) &&
    (!searchLower || entry.text.toLowerCase().includes(searchLower))
  )
  // 倒序只反转渲染顺序；相邻行的居中标题判断是对称的（前后都要求是分割线），不受影响。
  const ordered = descending ? [...visible].reverse().slice(0, LOG_ENTRY_LIMIT) : visible.slice(-LOG_ENTRY_LIMIT)

  /* 经典视图行数超过阈值时只渲染视口附近的行，其余用占位高度撑住滚动条。 */
  const virtualLines = viewMode === 'classic' && ordered.length >= VIRTUAL_LINE_THRESHOLD
  const lineHeights = useRef(new Map<number, number>())
  const lineNodes = useRef(new Map<Element, number>())
  const lineObserver = useRef<ResizeObserver | null>(null)
  const [lineVersion, setLineVersion] = useState(0)
  const [lineScroll, setLineScroll] = useState({top: 0, client: 0})

  useEffect(() => {
    if (!virtualLines) return
    const container = scroll.current
    if (!container) return
    const sync = () => setLineScroll({top: container.scrollTop, client: container.clientHeight})
    sync()
    let rafId: number | null = null
    const onScroll = () => {
      if (rafId !== null) return
      rafId = safeRaf(() => {
        rafId = null
        sync()
      })
    }
    container.addEventListener('scroll', onScroll, {passive: true})
    let observer: ResizeObserver | null = null
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(sync)
      observer.observe(container)
    }
    return () => {
      container.removeEventListener('scroll', onScroll)
      if (rafId !== null) safeCancelRaf(rafId)
      observer?.disconnect()
    }
  }, [virtualLines])

  /* 只观察窗口内已渲染的行：高度实测后替换占位值，未渲染的行继续用估算高度。 */
  useLayoutEffect(() => {
    if (!virtualLines || typeof ResizeObserver === 'undefined') return
    const container = scroll.current
    if (!container) return
    if (!lineObserver.current) {
      lineObserver.current = new ResizeObserver(entries => {
        let changed = false
        for (const entry of entries) {
          const id = lineNodes.current.get(entry.target)
          /* contentRect 不含 padding，行高要按 border box 取。 */
          const height = entry.borderBoxSize?.[0]?.blockSize ?? entry.contentRect.height
          if (id === undefined || height <= 0 || lineHeights.current.get(id) === height) continue
          lineHeights.current.set(id, height)
          changed = true
        }
        if (changed) setLineVersion(version => version + 1)
      })
    }
    const live = new Set<Element>()
    for (const node of container.querySelectorAll('[data-line-id]')) {
      live.add(node)
      lineNodes.current.set(node, Number((node as HTMLElement).dataset.lineId))
      lineObserver.current.observe(node)
    }
    for (const node of [...lineNodes.current.keys()]) {
      if (live.has(node)) continue
      lineObserver.current.unobserve(node)
      lineNodes.current.delete(node)
    }
  })

  useEffect(() => () => {
    lineObserver.current?.disconnect()
    lineObserver.current = null
  }, [])

  const lineLayout = useMemo(
    () => buildLineLayout(ordered, lineHeights.current, LINE_HEIGHT_ESTIMATE),
    [ordered, lineVersion]
  )

  const [lineStart, lineEnd] = virtualLines
    ? findVisibleRange(lineLayout.offsets, lineLayout.heights, lineScroll.top - OVERSCAN_BUFFER_PX, lineScroll.top + (lineScroll.client || 800) + OVERSCAN_BUFFER_PX, ordered.length)
    : [0, Math.max(0, ordered.length - 1)]

  function download() {
    flushBuffer.current()
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
        <button className="icon-button" onClick={toggleOrder} aria-label={ui('log.order')} aria-pressed={descending}
          title={descending ? ui('log.orderDesc') : ui('log.orderAsc')}>
          <ArrowDownUp size={15} />
        </button>
        <button
          className="icon-button"
          onClick={toggleViewMode}
          aria-label={viewMode === 'cards' ? ui('log.viewModeClassic') : ui('log.viewModeCards')}
          title={viewMode === 'cards' ? ui('log.viewModeCardsTitle') : ui('log.viewModeClassicTitle')}
        >
          {viewMode === 'cards' ? <LayoutGrid size={15} /> : <Terminal size={15} />}
        </button>
        <button
          className="icon-button"
          onClick={() => {
            const lastId = Math.max(
              entries.at(-1)?.id ?? 0,
              logBuffer.current.entries.at(-1)?.id ?? 0
            )
            flushBuffer.current()
            setFloor(lastId)
          }}
          aria-label={ui('log.clearView')}
        >
          <Trash2 size={15} />
        </button>
        <button className="text-button" onClick={download} aria-label={ui('log.export')}>
          <Download size={15} />{ui('log.exportShort')}
        </button>
      </div>
      {filtersOpen && <div className="log-filters" id="log-filters">
        <div className="relative flex-1">
          <Search size={15} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted-foreground"/>
          <Input className="pl-9" aria-label={ui('log.search')} placeholder={ui('log.searchPlaceholder')} value={search} onChange={event => setSearch(event.target.value)}/>
        </div>
        <Select aria-label={ui('log.level')} value={level} onChange={event => updateLevel(event.target.value)}>
          {LOG_LEVELS.map(item => (
            <option key={item} value={item}>{item === 'ALL' ? ui('log.allLevels') : item}</option>
          ))}
        </Select>
        <span>{ui('log.recent', {count: entries.length})}</span>
      </div>}
      <div className={`log-content ${viewMode === 'cards' ? 'log-cards-mode' : ''}`} ref={scroll} aria-label={ui('log.content')}>
        {visible.length ? (
          viewMode === 'cards' ? (
            <LogCardView entries={ordered} search={search} scrollRef={scroll} />
          ) : (
            <>
              {virtualLines && lineStart > 0 && <div style={{height: lineLayout.offsets[lineStart]}} aria-hidden="true" />}
              {ordered.slice(lineStart, lineEnd + 1).map((entry, offset) => {
                const index = lineStart + offset
                const prev = ordered[index - 1]
                const next = ordered[index + 1]
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
                    fresh={freshFrom.current !== null && entry.id > freshFrom.current}
                  />
                )
              })}
              {virtualLines && lineEnd < ordered.length - 1 && (
                <div style={{height: lineLayout.total - lineLayout.offsets[lineEnd] - lineLayout.heights[lineEnd]}} aria-hidden="true" />
              )}
            </>
          )
        ) : (
          <Empty icon={<Terminal size={26} />} title={entries.length ? ui('log.noMatch') : ui('log.ready')}>
            {entries.length ? ui('log.adjustFilter') : ui('log.waiting')}
          </Empty>
        )}
      </div>
    </section>
  )
}
