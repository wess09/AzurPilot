/**
 * @fileoverview 实例实时日志面板组件，及流式日志微批缓冲、行高布局等纯数据辅助。
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
import { LogCardView, findVisibleRange, logWindowTop, renderTokens, safeRaf, safeCancelRaf, OVERSCAN_BUFFER_PX } from './LogCardView'

/** 匹配标准日志行，捕获组依次为：等级、可选日期、时间、正文（以 │ 分隔）。 */
export const LOG_LINE_RE = /^([A-Z]{4,8})\s+(?:(\d{4}-\d{2}-\d{2})\s+)?(\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)\s*│\s*([\s\S]*)$/
/** 匹配带标题的分割线，捕获组 1 为标题文本。 */
export const RULE_RE = /^[═─]{3,}\s*(.*?)\s*[═─]{3,}$/
/** 匹配纯分割线：整行只有 ═ 或 ─。 */
export const PURE_RULE_RE = /^[═─]{3,}$/
/** 匹配居中标题：两侧各留 3+ 空格的单行文本，捕获组 1 为标题。 */
export const CENTER_TITLE_RE = /^\s{3,}(.*?)\s{3,}$/
/** 客户端独立的日志条数防御上限，背景见 mergeLogEntries 说明。 */
export const LOG_ENTRY_LIMIT = 1000
// 连续推送时每 50ms 最多提交一次日志列表，给滚动和拖拽留出渲染时间。
const LOG_RENDER_INTERVAL_MS = 50
const VIRTUAL_LINE_THRESHOLD = 120
/* 未实测到高度的日志行先按这个值占位，实测后替换。 */
export const LINE_HEIGHT_ESTIMATE = 18

/** 日志跟随的每帧步长上限（像素）；距离更近时按距离收比例。 */
export const MAX_FOLLOW_STEP = 24

/** 日志微批缓冲状态：entries 为待合并的行，reset 置位表示下批先清空重放，cursor 为服务端游标。 */
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
  const incoming = data.entries.slice(-LOG_ENTRY_LIMIT)
  if (data.reset) {
    buffer.reset = true
    buffer.entries = incoming
  } else {
    buffer.entries.push(...incoming)
    if (buffer.entries.length > LOG_ENTRY_LIMIT) buffer.entries.splice(0, buffer.entries.length - LOG_ENTRY_LIMIT)
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
  // previous 来自上一次合并，已按 id 升序且去重。正常增量只需拼接尾部。
  const retained = reset ? [] : previous
  const lastId = retained.at(-1)?.id ?? -Infinity
  if (recent.every((entry, index) => entry.id > (index ? recent[index - 1].id : lastId))) {
    if (!recent.length) return retained
    return retained.slice(Math.max(0, retained.length + recent.length - LOG_ENTRY_LIMIT)).concat(recent)
  }
  const entries = new Map<number, LogEntry>()
  if (!reset) for (const entry of previous.slice(-LOG_ENTRY_LIMIT)) entries.set(entry.id, entry)
  for (const entry of recent) entries.set(entry.id, entry)
  return [...entries.values()].sort((a, b) => a.id - b.id).slice(-LOG_ENTRY_LIMIT)
}

/**
 * 单行日志的判定与渲染：依次识别纯分割线、带标题分割线、标准等级行、居中标题，
 * 其余（多行文本、Traceback 等非标准行）按原文渲染；搜索高亮由 renderTokens 统一处理。
 *
 * @param isCenter 调用方按上下文（前后行均为双线分割）给出的居中标记。
 * @param fresh 行 id 大于已渲染最大 id 时为 true，仅用于入场动画。
 */
export const LogLine = memo(function LogLine({entry, search, isCenter, fresh}: {entry: LogEntry; search: string; isCenter?: boolean; fresh?: boolean}) {
  const rawText = entry.text.replace(/[\r\n]+$/, '')
  const trimmed = rawText.trim()
  const freshClass = fresh ? ' motion-enter' : ''

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

  // RULE_RE 对纯分割线也会命中（标题捕获为空），要求标题非空才算带线标题。
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

  return (
    <div className={`log-line log-entry-line log-raw level-${entry.level.toLowerCase()}${freshClass}`} data-line-id={entry.id}>
      <span className="log-msg">{renderTokens(rawText, search)}</span>
    </div>
  )
})

const LOG_LEVELS = ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

function filterLogEntries(entries: LogEntry[], floor: number, level: string, search: string) {
  if ((entries[0]?.id ?? Infinity) > floor && level === 'ALL' && !search) return entries
  return entries.filter(entry =>
    entry.id > floor &&
    (level === 'ALL' || entry.level === level) &&
    (!search || entry.text.toLowerCase().includes(search))
  )
}

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

/**
 * 实例实时日志面板：优先消费外部传入的 logs 流，否则自行拉取初始日志并订阅推送事件；
 * 提供搜索、等级过滤、正倒序、跟随滚动与卡片/经典两种视图。
 *
 * @param active 面板是否在前台；false 时暂停跟随滚动。
 * @param logs 外部注入的日志流；提供后组件不再自行订阅推送，仅接受该实例的日志。
 */
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

  const logBuffer = useRef<LogBufferState & { timer: ReturnType<typeof setTimeout> | null }>({
    entries: [],
    reset: false,
    cursor: null,
    timer: null,
  })

  const flushBuffer = useRef(() => {})
  flushBuffer.current = () => {
    const buf = logBuffer.current
    if (buf.timer !== null) {
      clearTimeout(buf.timer)
      buf.timer = null
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
      try { localStorage.setItem('azurpilot.log.viewMode', next) } catch { /* 存储不可用时仅本次会话生效。 */ }
      return next
    })
  }

  function toggleOrder() {
    setDescending(previous => {
      const next = !previous
      try { localStorage.setItem(`azurpilot.log.order.${instance}`, next ? 'desc' : 'asc') } catch { /* 存储不可用时仅本次会话生效。 */ }
      return next
    })
  }

  useEffect(() => {
    if (connection !== 'ready' || external) return
    let active = true
    const buf = logBuffer.current
    if (buf.timer !== null) {
      clearTimeout(buf.timer)
      buf.timer = null
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
      if (buf.timer !== null) {
        clearTimeout(buf.timer)
        buf.timer = null
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

      if (buf.timer === null) buf.timer = setTimeout(() => flushBuffer.current(), LOG_RENDER_INTERVAL_MS)
    })

    return () => {
      unsubscribe()
      const buf = logBuffer.current
      if (buf.timer !== null) {
        clearTimeout(buf.timer)
        buf.timer = null
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
    // 量与写都放进 rAF：layout effect 阶段刚改完 DOM，此刻读 scrollHeight 会强制同步布局；
    // 每帧只在帧首读一次 scrollTop、帧尾写一次。
    // 只改日志容器自身的滚动位置，不会像尾部元素的 scrollIntoView 那样连带滚动整个页面。
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
  const visible = useMemo(() => filterLogEntries(entries, floor, level, searchLower), [entries, floor, level, searchLower])
  // 倒序只反转渲染顺序；相邻行的居中标题判断是对称的（前后都要求是分割线），不受影响。
  const ordered = useMemo(() => descending ? [...visible].reverse() : visible, [descending, visible])

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
    const sync = () => {
      const top = logWindowTop(container.scrollTop)
      const client = container.clientHeight
      setLineScroll(previous => previous.top === top && previous.client === client ? previous : {top, client})
    }
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

  useEffect(() => {
    const heights = lineHeights.current
    if (heights.size <= 2 * LOG_ENTRY_LIMIT) return
    const retained = new Set(entries.map(entry => entry.id))
    for (const id of heights.keys()) {
      if (!retained.has(id)) heights.delete(id)
    }
    setLineVersion(version => version + 1)
  }, [entries])

  const lineLayout = useMemo(
    () => virtualLines ? buildLineLayout(ordered, lineHeights.current, LINE_HEIGHT_ESTIMATE) : null,
    [ordered, lineVersion, virtualLines]
  )

  // clientHeight 首次量到前为 0，按 800 兜底一屏高度。
  const [lineStart, lineEnd] = lineLayout
    ? findVisibleRange(lineLayout.offsets, lineLayout.heights, lineScroll.top - OVERSCAN_BUFFER_PX, lineScroll.top + (lineScroll.client || 800) + OVERSCAN_BUFFER_PX, ordered.length)
    : [0, Math.max(0, ordered.length - 1)]

  function download() {
    const {entries: pending, reset, cursor} = logBuffer.current
    const exported = cursor === null ? visible : filterLogEntries(
      mergeLogEntries(entries, pending, reset), cursor < floor ? 0 : floor, level, searchLower,
    )
    flushBuffer.current()
    const url = URL.createObjectURL(new Blob([exported.map(entry => entry.text).join('\n')], {type: 'text/plain;charset=utf-8'}))
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
              {lineLayout && lineStart > 0 && <div style={{height: lineLayout.offsets[lineStart]}} aria-hidden="true" />}
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
              {lineLayout && lineEnd < ordered.length - 1 && (
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
