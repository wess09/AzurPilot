/**
 * @fileoverview 结构化运行日志卡片流渲染与虚拟滚动视图组件。
 */

import {
  Fragment,
  useState,
  useMemo,
  useEffect,
  useLayoutEffect,
  useRef,
  useCallback,
  memo,
  type ReactNode,
  type RefObject,
} from 'react'
import {
  AlertCircle,
  Anchor,
  Ban,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  Compass,
  Copy,
  Crown,
  HelpCircle,
  Layers,
  Map as MapIcon,
  Package,
  PawPrint,
  Radar,
  Ship,
  Skull,
  Sparkles,
  Swords,
  Table as TableIcon,
  Terminal,
  Crosshair,
  Zap,
} from 'lucide-react'
import type { LogEntry } from '../api/types'
import { LazyMarkdown } from './LazyMarkdown'

// 提取日志消息正文（剥离 LEVEL HH:MM:SS.mmm │ 前缀）。
function extractLogMessage(raw: string): { level: string; time: string; message: string } {
  const match = /^([A-Z]{4,8})\s+(?:(\d{4}-\d{2}-\d{2})\s+)?(\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)\s*│\s*([\s\S]*)$/.exec(raw)
  if (match) {
    return { level: match[1], time: match[3], message: match[4] }
  }
  return { level: 'INFO', time: '', message: raw }
}

// 词法高亮正则常量（避免重复实例化 RegExp）。
const TOKEN_REGEX = /(\b(?:True|False|None)\b)|(<<<[\s\S]*?>>>)|(\[[a-zA-Z0-9_.\u4e00-\u9fff-]+\])|([\{\}\[\]\(\)])|((?:[a-zA-Z]:[/\\]|(?:\.{1,2}[/\\]|[/\\]))[\w.\-/\\]+)|(\b\d{2}:\d{2}:\d{2}(?:\.\d+)?\b)/g

/** 词法解析与高亮结果缓存的容量上限；缓存键为 text + '\0' + search。 */
export const TOKEN_CACHE_MAX = 2000
const tokenCache = new Map<string, ReactNode>()

/** 清空词法高亮缓存；测试间隔离与内存回收用。 */
export function clearTokenCache(): void {
  tokenCache.clear()
}

/** 读取当前词法高亮缓存的条目数；测试断言缓存行为用。 */
export function getTokenCacheSize(): number {
  return tokenCache.size
}

function getCachedTokens(key: string): ReactNode | undefined {
  const cached = tokenCache.get(key)
  if (cached !== undefined) {
    // 提升最近访问项到尾部。
    tokenCache.delete(key)
    tokenCache.set(key, cached)
    return cached
  }
  return undefined
}

function setCachedTokens(key: string, node: ReactNode): void {
  if (tokenCache.has(key)) {
    tokenCache.delete(key)
  } else if (tokenCache.size >= TOKEN_CACHE_MAX) {
    // 淘汰最久未访问的首项。
    const oldestKey = tokenCache.keys().next().value
    if (oldestKey !== undefined) {
      tokenCache.delete(oldestKey)
    }
  }
  tokenCache.set(key, node)
}

/** 把一行日志文本做词法高亮（布尔值、[标签]、括号、路径、时间戳），并叠加搜索词高亮；结果走 LRU 缓存。 */
export function renderTokens(text: string, search = ''): ReactNode {
  if (!text) return null
  const cacheKey = text + '\0' + search
  const cached = getCachedTokens(cacheKey)
  if (cached !== undefined) {
    return cached
  }

  const searchLower = search.trim().toLowerCase()
  // 正则带 g 标志且跨调用复用，exec 的 lastIndex 要先归零。
  TOKEN_REGEX.lastIndex = 0

  const nodes: ReactNode[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = TOKEN_REGEX.exec(text)) !== null) {
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

  const result = <>{nodes}</>
  setCachedTokens(cacheKey, result)
  return result
}

function renderSearchHighlights(text: string, searchLower: string, keyPrefix: string): ReactNode {
  if (!text) return null
  if (!searchLower) return <Fragment key={keyPrefix}>{text}</Fragment>
  const lower = text.toLowerCase()
  const idx = lower.indexOf(searchLower)
  if (idx === -1) return <Fragment key={keyPrefix}>{text}</Fragment>

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


function isAsciiDigits(value: string, minLength: number, maxLength: number): boolean {
  if (value.length < minLength || value.length > maxLength) return false
  for (const char of value) {
    if (char < '0' || char > '9') return false
  }
  return true
}

function isCostValue(value: string): boolean {
  return value === '-' || value === '--' || isAsciiDigits(value, 1, 4)
}

function CopyButton({ text, label = '复制' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  function handleCopy(e: React.MouseEvent) {
    e.stopPropagation()
    void navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button className="card-btn-action" onClick={handleCopy} title="复制内容">
      {copied ? <Check size={12} className="text-success" /> : <Copy size={12} />}
      <span>{copied ? '已复制' : label}</span>
    </button>
  )
}

// 聚合卡片数据模型

type CardItem =
  | {
      type: 'map_grid'
      id: number
      time: string
      cols: string[]
      rows: Array<{ rowNum: number; cells: string[] }>
      rawText: string
    }
  | {
      type: 'cost_grid'
      id: number
      time: string
      cols: string[]
      rows: Array<{ rowNum: number; values: string[] }>
      rawText: string
    }
  | {
      type: 'matrix_grid'
      id: number
      time: string
      title: string
      rows: string[][]
      rawText: string
    }
  | {
      type: 'perspective'
      id: number
      time: string
      model: '透视' | '单应性'
      duration: string
      lowerEdge: boolean
      leftEdge: boolean
      upperEdge: boolean
      rightEdge: boolean
      info1: string
      info2: string
      rawText: string
    }
  | {
      type: 'property_sheet'
      id: number
      time: string
      items: Array<{ key: string; value: string }>
      rawText: string
    }
  | {
      type: 'data_table'
      id: number
      time: string
      title: string
      headers: string[]
      rows: string[][]
      rawText: string
    }
  | {
      type: 'error_context'
      id: number
      time: string
      title: string
      reason: string
      impact: string
      action: string
      exception: string
      stackTrace: string
      rawText: string
    }
  | {
      type: 'traceback'
      id: number
      time: string
      excName: string
      rawText: string
    }
  | {
      type: 'llm_report'
      id: number
      time: string
      model: string
      content: string
      rawText: string
    }
  | {
      type: 'system_banner'
      id: number
      time: string
      title: string
      rawText: string
    }
  | {
      type: 'stage_header'
      id: number
      time: string
      title: string
      level: 1 | 2
      rawText: string
    }
  | {
      type: 'single'
      id: number
      entry: LogEntry
      time: string
      level: string
      message: string
      rawText: string
    }

// 流式块级聚合状态机

interface CardRange {
  card: CardItem
  start: number
  end: number
}

/** 从 startIndex 起把日志条目聚合成卡片：每个分支识别后端日志的一种排版模式，都不命中就落回单行卡片。 */
function aggregateSlice(
  entries: LogEntry[],
  startIndex = 0,
  endIndex = entries.length,
): { cards: CardItem[]; ranges: CardRange[] } {
  const cards: CardItem[] = []
  const ranges: CardRange[] = []
  let index = startIndex

  while (index < endIndex) {
    const cardStart = index
    const entry = entries[index]
    const raw = entry.text.replace(/[\r\n]+$/, '')
    const { level, time, message } = extractLogMessage(raw)
    const trimmedMsg = message.trim()

    // 1. 系统级横幅（Level 0 HR：═ + 居中文本 + ═）。
    if (
      trimmedMsg.includes('═'.repeat(10)) &&
      index + 2 < entries.length
    ) {
      const next1 = extractLogMessage(entries[index + 1].text).message.trim()
      const next2 = extractLogMessage(entries[index + 2].text).message.trim()
      if (next2.includes('═'.repeat(10)) && next1 && !next1.includes('═')) {
        const card: CardItem = {
          type: 'system_banner',
          id: entry.id,
          time,
          title: next1,
          rawText: [entry.text, entries[index + 1].text, entries[index + 2].text].join('\n'),
        }
        index += 3
        cards.push(card)
        ranges.push({ card, start: cardStart, end: index })
        continue
      }
    }

    // 2. 任务/阶段带线标题（Level 1/2 HR：═ TITLE ═ + 紧随其后的同名 INFO）。
    const ruleMatch = /^[═─]{3,}\s*(.*?)\s*[═─]{3,}$/.exec(trimmedMsg)
    if (ruleMatch && ruleMatch[1].trim()) {
      const title = ruleMatch[1].trim()
      const isDouble = trimmedMsg.includes('═')
      // 检查下一行是否重复输出了同名 INFO。
      let rawText = entry.text
      if (index + 1 < entries.length) {
        const nextMsg = extractLogMessage(entries[index + 1].text).message.trim()
        if (nextMsg === title) {
          rawText += '\n' + entries[index + 1].text
          index++
        }
      }
      index++
      const card: CardItem = {
        type: 'stage_header',
        id: entry.id,
        time,
        title,
        level: isDouble ? 1 : 2,
        rawText,
      }
      cards.push(card)
      ranges.push({ card, start: cardStart, end: index })
      continue
    }

    // 3. 海域透视与边缘线识别：[地图-透视] 或 [地图-单应性]。
    const perspMatch = /^\[地图-(透视|单应性)\]\s+([\d.]+s)\s+(_)?\s*(水平:.*|边缘线:.*)$/.exec(trimmedMsg)
    if (perspMatch && index + 1 < entries.length) {
      const nextMsg = extractLogMessage(entries[index + 1].text).message
      const nextPersp = /^\[地图-(透视|单应性)\]\s+边缘:\s*([\/ _\\]*?)\s+(垂直:.*|单应位置:.*)$/.exec(nextMsg.trim())
      if (nextPersp) {
        const edgesStr = nextPersp[2]
        const card: CardItem = {
          type: 'perspective',
          id: entry.id,
          time,
          model: perspMatch[1] as '透视' | '单应性',
          duration: perspMatch[2],
          lowerEdge: perspMatch[3] === '_',
          leftEdge: edgesStr.includes('/'),
          upperEdge: edgesStr.includes('_'),
          rightEdge: edgesStr.includes('\\'),
          info1: perspMatch[4],
          info2: nextPersp[3],
          rawText: entry.text + '\n' + entries[index + 1].text,
        }
        index += 2
        cards.push(card)
        ranges.push({ card, start: cardStart, end: index })
        continue
      }
    }

    // 4. 全局海图主网格：[地图-显示] 行头 + A  B  C  D 列头。
    const mapHeaderMatch = /^\[地图-显示\]\s+([A-Z](\s+[A-Z])+)/.exec(trimmedMsg)
    if (mapHeaderMatch) {
      const cols = mapHeaderMatch[1].trim().split(/\s+/)
      const rows: Array<{ rowNum: number; cells: string[] }> = []
      const rawLines = [entry.text]
      let rIdx = index + 1

      while (rIdx < entries.length) {
        const rMsg = extractLogMessage(entries[rIdx].text).message
        const rowMatch = /^\s*(\d{1,2})\s+(([A-Za-z0-9_=+-]{2}\s*)+)$/.exec(rMsg)
        if (rowMatch) {
          const rowNum = parseInt(rowMatch[1], 10)
          const cells = rowMatch[2].trim().split(/\s+/)
          rows.push({ rowNum, cells })
          rawLines.push(entries[rIdx].text)
          rIdx++
        } else {
          break
        }
      }

      if (rows.length > 0) {
        index = rIdx
        const card: CardItem = {
          type: 'map_grid',
          id: entry.id,
          time,
          cols,
          rows,
          rawText: rawLines.join('\n'),
        }
        cards.push(card)
        ranges.push({ card, start: cardStart, end: index })
        continue
      }
    }

    // 5. 寻路代价网格（Cost Map）：大间距字母列头 + 行号数字行。
    const costHeaderMatch = /^\s*([A-Z](\s{2,}[A-Z])+)/.exec(trimmedMsg)
    if (costHeaderMatch && index + 1 < entries.length) {
      const cols = costHeaderMatch[1].trim().split(/\s+/)
      const rows: Array<{ rowNum: number; values: string[] }> = []
      const rawLines = [entry.text]
      let rIdx = index + 1

      while (rIdx < entries.length) {
        const rMsg = extractLogMessage(entries[rIdx].text).message
        const fields = rMsg.trim().split(/[ \t]+/).filter(Boolean)
        const rowToken = fields[0] ?? ''
        const values = fields.slice(1)
        if (isAsciiDigits(rowToken, 1, 2) && values.length > 0 && values.every(isCostValue)) {
          const rowNum = Number(rowToken)
          rows.push({ rowNum, values })
          rawLines.push(entries[rIdx].text)
          rIdx++
        } else {
          break
        }
      }

      if (rows.length > 0) {
        index = rIdx
        const card: CardItem = {
          type: 'cost_grid',
          id: entry.id,
          time,
          cols,
          rows,
          rawText: rawLines.join('\n'),
        }
        cards.push(card)
        ranges.push({ card, start: cardStart, end: index })
        continue
      }
    }

    // 6. 局部视野或雷达矩阵（View.show / Radar.show）：连续多行两字符单元格（无行号）。
    const matrixRowMatch = /^\s*(([A-Za-z0-9_=+-]{2}|\.\.)\s+){3,}([A-Za-z0-9_=+-]{2}|\.\.)\s*$/.exec(trimmedMsg)
    if (matrixRowMatch && !/^\s*\d+/.test(trimmedMsg)) {
      const rows: string[][] = [trimmedMsg.split(/\s+/)]
      const rawLines = [entry.text]
      let rIdx = index + 1

      while (rIdx < entries.length) {
        const rMsg = extractLogMessage(entries[rIdx].text).message.trim()
        if (/^(([A-Za-z0-9_=+-]{2}|\.\.)\s*){3,}$/.test(rMsg) && !/^\d+/.test(rMsg)) {
          rows.push(rMsg.split(/\s+/))
          rawLines.push(entries[rIdx].text)
          rIdx++
        } else {
          break
        }
      }

      if (rows.length >= 3) {
        index = rIdx
        const card: CardItem = {
          type: 'matrix_grid',
          id: entry.id,
          time,
          title: rows[0].includes('..') ? '局部海域扫描切片 (Local View)' : '大世界战略雷达扫描 (Radar Map)',
          rows,
          rawText: rawLines.join('\n'),
        }
        cards.push(card)
        ranges.push({ card, start: cardStart, end: index })
        continue
      }
    }

    // 7. 连续右对齐属性块（attr_align: key: val）。
    const attrMatch = /^\s*([^:\n]{2,22}):\s*(.+)$/.exec(trimmedMsg)
    if (attrMatch && !trimmedMsg.startsWith('http') && !trimmedMsg.startsWith('E:') && !trimmedMsg.startsWith('C:')) {
      const items = [{ key: attrMatch[1].trim(), value: attrMatch[2].trim() }]
      const rawLines = [entry.text]
      let rIdx = index + 1

      while (rIdx < entries.length) {
        const rMsg = extractLogMessage(entries[rIdx].text).message.trim()
        const nextAttr = /^\s*([^:\n]{2,22}):\s*(.+)$/.exec(rMsg)
        if (nextAttr && !rMsg.startsWith('http') && !rMsg.startsWith('E:') && !rMsg.startsWith('C:')) {
          items.push({ key: nextAttr[1].trim(), value: nextAttr[2].trim() })
          rawLines.push(entries[rIdx].text)
          rIdx++
        } else {
          break
        }
      }

      if (items.length >= 2) {
        index = rIdx
        const card: CardItem = {
          type: 'property_sheet',
          id: entry.id,
          time,
          items,
          rawText: rawLines.join('\n'),
        }
        cards.push(card)
        ranges.push({ card, start: cardStart, end: index })
        continue
      }
    }

    // 8. 数据表格（Rich Table / ASCII Table）。
    const hasUnicodeBox =
      (raw.includes('┌') && raw.includes('┘') && raw.includes('│')) ||
      (raw.includes('╭') && raw.includes('╯') && raw.includes('│') && !raw.includes('Traceback')) ||
      (raw.includes('┏') && raw.includes('┛') && raw.includes('┃')) ||
      (raw.includes('╔') && raw.includes('╝') && raw.includes('║'))
    const hasAsciiBox = /\+[-=]{3,}\+/.test(raw) && (raw.match(/\|/g) || []).length >= 4

    if (hasUnicodeBox || hasAsciiBox) {
      const vSep = raw.includes('│') ? '│' : raw.includes('┃') ? '┃' : raw.includes('║') ? '║' : '|'
      const lines = raw.split('\n')
      let title = '数据表格'
      let headers: string[] = []
      const rows: string[][] = []

      for (let i = 0; i < lines.length; i++) {
        const l = lines[i].trim()
        if (
          l &&
          !l.includes('┌') && !l.includes('┐') && !l.includes('└') && !l.includes('┘') &&
          !l.includes('╭') && !l.includes('╮') && !l.includes('╰') && !l.includes('╯') &&
          !l.includes('┏') && !l.includes('┛') && !l.includes('╔') && !l.includes('╝') &&
          !l.startsWith('+--') && !l.startsWith('+==') &&
          !l.includes(vSep) &&
          i < 3
        ) {
          title = l
        } else if (l.includes(vSep) && headers.length === 0) {
          const cells = l.split(vSep).slice(1, -1).map(s => s.trim())
          if (cells.length > 0 && !cells.every(c => !c)) {
            headers = cells
          }
        } else if (l.includes(vSep)) {
          const cells = l.split(vSep).slice(1, -1).map(s => s.trim())
          if (cells.length > 0 && !cells.every(c => !c)) {
            if (!cells.every(c => /^[-=]+$/.test(c))) {
              rows.push(cells)
            }
          }
        }
      }

      if (headers.length > 0) {
        index++
        const card: CardItem = {
          type: 'data_table',
          id: entry.id,
          time,
          title,
          headers,
          rows,
          rawText: raw,
        }
        cards.push(card)
        ranges.push({ card, start: cardStart, end: index })
        continue
      }
    }

    // 9. 统一错误上下文（error_context）：包含 [错误] 与 原因/建议。
    if (raw.includes('[错误]') && (raw.includes('原因：') || raw.includes('建议：'))) {
      const lines = raw.split('\n')
      let title = '运行时异常'
      let reason = ''
      let impact = ''
      let action = ''
      let exception = ''
      const stackLines: string[] = []
      let inStack = false

      for (const line of lines) {
        const trimmed = line.trim()
        if (trimmed.startsWith('[错误]')) {
          title = trimmed.replace('[错误]', '').trim()
        } else if (trimmed.startsWith('原因：')) {
          reason = trimmed.replace('原因：', '').trim()
        } else if (trimmed.startsWith('影响：')) {
          impact = trimmed.replace('影响：', '').trim()
        } else if (trimmed.startsWith('建议：')) {
          action = trimmed.replace('建议：', '').trim()
        } else if (trimmed.startsWith('异常：')) {
          exception = trimmed.replace('异常：', '').trim()
        } else if (trimmed.includes('Traceback') || inStack) {
          inStack = true
          stackLines.push(line)
        }
      }

      index++
      const card: CardItem = {
        type: 'error_context',
        id: entry.id,
        time,
        title,
        reason,
        impact,
        action,
        exception,
        stackTrace: stackLines.join('\n'),
        rawText: raw,
      }
      cards.push(card)
      ranges.push({ card, start: cardStart, end: index })
      continue
    }

    // 10. 独立异常堆栈（Traceback）。
    if (raw.includes('Traceback (most recent call last)')) {
      const excMatch = /([a-zA-Z0-9_]+Error|[a-zA-Z0-9_]+Exception|ScriptEnd):\s*(.*)$/.exec(raw)
      index++
      const card: CardItem = {
        type: 'traceback',
        id: entry.id,
        time,
        excName: excMatch ? `${excMatch[1]}: ${excMatch[2]}` : 'Python 异常堆栈',
        rawText: raw,
      }
      cards.push(card)
      ranges.push({ card, start: cardStart, end: index })
      continue
    }

    // 11. LLM 智能分析报告。
    if (raw.includes('[LLM 分析报告') || raw.includes('[LLM] LLM 错误分析')) {
      const lines = raw.split('\n')
      const filtered: string[] = []
      let model = 'gpt-4o-mini'
      for (const line of lines) {
        const trimmed = line.trim()
        const modelMatch = trimmed.match(/由\s*([a-zA-Z0-9_.-]+)\s*提供/)
        if (modelMatch) {
          model = modelMatch[1]
        }
        if (/^[A-Z]{4,8}\s+.*?[│]\s*\[LLM\]\s*$/.test(trimmed) || trimmed === '[LLM]') continue
        if (trimmed.startsWith('[LLM 分析报告') || trimmed.startsWith('[LLM] 分析结束')) continue
        filtered.push(line)
      }
      const content = filtered.join('\n').trim()

      index++
      const card: CardItem = {
        type: 'llm_report',
        id: entry.id,
        time,
        model,
        content,
        rawText: raw,
      }
      cards.push(card)
      ranges.push({ card, start: cardStart, end: index })
      continue
    }

    // 12. 默认：常规单行日志卡片。
    index++
    const card: CardItem = {
      type: 'single',
      id: entry.id,
      entry,
      time,
      level,
      message,
      rawText: raw,
    }
    cards.push(card)
    ranges.push({ card, start: cardStart, end: index })
  }

  return { cards, ranges }
}

// 增量聚合缓存：记住上次的输入与结果，日志追加时避免全量重算。
let lastEntries: LogEntry[] = []
let lastRanges: CardRange[] = []
let lastCards: CardItem[] = []

/** 清空增量聚合缓存；测试间隔离用。 */
export function clearAggregationCache(): void {
  lastEntries = []
  lastRanges = []
  lastCards = []
}

/** 读取增量聚合缓存的卡片数与日志条数；测试断言缓存行为用。 */
export function getAggregationCacheInfo(): {
  cachedCardsCount: number
  cachedEntriesCount: number
} {
  return {
    cachedCardsCount: lastCards.length,
    cachedEntriesCount: lastEntries.length,
  }
}

/** 持续追加日志时复用未变的卡片，缓冲区淘汰旧条目后仍可复用重叠部分。 */
export function aggregateEntriesToCards(entries: LogEntry[]): CardItem[] {
  if (!entries || entries.length === 0) {
    lastEntries = []
    lastRanges = []
    lastCards = []
    return []
  }

  // 1. 同一数组引用直接复用上次结果。
  if (entries === lastEntries) {
    return lastCards
  }

  const dropped = lastEntries.findIndex(entry => entry.id === entries[0].id)
  const overlap = lastEntries.length - dropped
  if (dropped >= 0 && entries.length >= overlap) {
    let matched = 0
    while (matched < overlap) {
      const entry = entries[matched]
      const cached = lastEntries[dropped + matched]
      if (entry !== cached && (entry.id !== cached.id || entry.text !== cached.text || entry.level !== cached.level)) break
      matched++
    }
    if (matched === overlap) {
      if (dropped === 0 && entries.length === overlap) return lastCards

      // 末尾四张重新解析，允许追加条目补全横幅、海图和属性块。
      const tailIndex = lastRanges.length - 4
      const reuseIndex = lastRanges.findIndex(range => range.start >= dropped)
      if (reuseIndex >= 0 && reuseIndex < tailIndex) {
        const headEnd = lastRanges[reuseIndex].start - dropped
        const head = aggregateSlice(entries, 0, headEnd)
        // 裁剪若切开多行卡片，重新解析的首张卡片可能跨过旧边界。
        if ((head.ranges.at(-1)?.end ?? 0) === headEnd) {
          const tail = aggregateSlice(entries, lastRanges[tailIndex].start - dropped)
          const ranges = lastRanges.slice(reuseIndex, tailIndex)
          const shifted = dropped ? ranges.map(({card, start, end}) => ({card, start: start - dropped, end: end - dropped})) : ranges
          lastRanges = head.ranges.concat(shifted, tail.ranges)
          lastCards = head.cards.concat(lastCards.slice(reuseIndex, tailIndex), tail.cards)
          lastEntries = entries
          return lastCards
        }
      }
    }
  }

  const full = aggregateSlice(entries)
  lastCards = full.cards
  lastRanges = full.ranges
  lastEntries = entries
  return lastCards
}

// 语义色彩与 Tooltip 释义词典

const CELL_DICT: Record<string, { label: string; cls: string }> = {
  '++': { label: '陆地/不可通航', cls: 'cell-land' },
  '--': { label: '海洋/安全航道', cls: 'cell-sea' },
  '..': { label: '视野盲区/未检测', cls: 'cell-blind' },
  '==': { label: '已清除/已扫描', cls: 'cell-cleared' },
  'FL': { label: '第一舰队旗舰 (当前控制)', cls: 'cell-fleet-1' },
  'Fl': { label: '第二舰队', cls: 'cell-fleet-2' },
  'ss': { label: '潜艇部队', cls: 'cell-submarine' },
  'BO': { label: '关卡旗舰 Boss', cls: 'cell-boss' },
  'MY': { label: '神秘问号调查点', cls: 'cell-mystery' },
  'AM': { label: '弹药补给点', cls: 'cell-ammo' },
  'FR': { label: '机械要塞', cls: 'cell-fortress' },
  'MI': { label: '导弹支援点', cls: 'cell-missile' },
  'Fc': { label: '被塞壬捕获 (移动受限)', cls: 'cell-caught' },
  'SU': { label: '塞壬精英敌人', cls: 'cell-siren' },
  'AK': { label: '明石隐藏商店', cls: 'cell-akashi' },
  'AL': { label: '护送盟友货船', cls: 'cell-ally' },
  'RE': { label: '大世界资源箱', cls: 'cell-resource' },
  'EX': { label: '大世界感叹号特殊事件', cls: 'cell-event' },
  'ME': { label: '大世界指挥喵搜索点', cls: 'cell-meowfficer' },
  'QU': { label: '神秘问号事件', cls: 'cell-question' },
  'SD': { label: '大世界环境扫描装置', cls: 'cell-device' },
  'AR': { label: '大世界机密档案记录', cls: 'cell-archive' },
  'PO': { label: '大世界补给港口', cls: 'cell-port' },
  'EN': { label: '敌方舰队', cls: 'cell-enemy' },
}

function getCellMeta(code: string): { label: string; cls: string } {
  if (CELL_DICT[code]) return CELL_DICT[code]
  if (/^[0-3][LMCET]/.test(code)) {
    const star = code[0]
    const genreMap: Record<string, string> = { L: '轻型巡逻', M: '主力战列', C: '航空航母', E: '未知敌舰', T: '运输舰队' }
    const genre = genreMap[code[1]] || '敌舰'
    return { label: `${star}★ ${genre}敌舰`, cls: 'cell-enemy' }
  }
  return { label: `未知标记 (${code})`, cls: 'cell-default' }
}

export function renderCellContent(code: string): ReactNode {
  // 1. 敌舰：行首 0-3 星数 + 舰种字母（1M、2C、3E…），EN 也是敌舰。
  if (/^[0-3][LMCET]/.test(code) || code === 'EN') {
    const star = code[0]
    return (
      <span className="cell-icon-wrap" title={`${star === 'E' ? '' : star + '★ '}敌舰 (${code})`}>
        <Swords size={13} className="cell-icon" />
        {star !== '0' && star !== 'E' && <span className="cell-sub-star">{star}</span>}
      </span>
    )
  }
  if (code === 'SU') {
    return (
      <span className="cell-icon-wrap" title="塞壬精英敌人 (SU)">
        <Skull size={13} className="cell-icon" />
      </span>
    )
  }

  if (code === 'BO') {
    return (
      <span className="cell-icon-wrap" title="关卡旗舰 Boss (BO)">
        <Crown size={14} className="cell-icon" />
      </span>
    )
  }

  if (code === 'FL' || code === 'Fl') {
    return (
      <span className="cell-icon-wrap" title="主力舰队旗舰 (FL)">
        <Ship size={13} className="cell-icon" />
      </span>
    )
  }
  if (code === 'ss') {
    return (
      <span className="cell-icon-wrap" title="潜艇部队 (ss)">
        <Anchor size={13} className="cell-icon" />
      </span>
    )
  }

  if (code === '++') {
    return (
      <span className="cell-icon-wrap" title="不可通航陆地/障碍 (++)">
        <Ban size={12} className="cell-icon" />
      </span>
    )
  }
  if (code === 'Fc') {
    return (
      <span className="cell-icon-wrap" title="被塞壬捕获/移动受限 (Fc)">
        <Ban size={12} className="cell-icon" />
      </span>
    )
  }
  if (code === 'FR') {
    return (
      <span className="cell-icon-wrap" title="机械要塞不可走 (FR)">
        <Ban size={12} className="cell-icon" />
      </span>
    )
  }

  // 5. 海域与已扫格（--、==）不画图标，只留 getCellMeta 给的底色。
  if (code === '--' || code === '==') {
    return null
  }

  if (code === 'ME') {
    return (
      <span className="cell-icon-wrap" title="大世界指挥喵搜索点 (ME)">
        <PawPrint size={13} className="cell-icon" />
      </span>
    )
  }
  if (code === 'EX') {
    return (
      <span className="cell-icon-wrap" title="大世界感叹号特殊事件 (EX)">
        <AlertCircle size={13} className="cell-icon" />
      </span>
    )
  }
  if (code === 'SD') {
    return (
      <span className="cell-icon-wrap" title="大世界环境扫描探测装置 (SD)">
        <Radar size={13} className="cell-icon" />
      </span>
    )
  }
  if (code === 'AR') {
    return (
      <span className="cell-icon-wrap" title="大世界机密档案记录 (AR)">
        <BookOpen size={13} className="cell-icon" />
      </span>
    )
  }
  if (code === 'PO') {
    return (
      <span className="cell-icon-wrap" title="大世界补给港口 (PO)">
        <Anchor size={13} className="cell-icon" />
      </span>
    )
  }

  if (code === 'MY' || code === 'QU') {
    return (
      <span className="cell-icon-wrap" title="神秘问号调查点 (MY/QU)">
        <HelpCircle size={13} className="cell-icon" />
      </span>
    )
  }
  if (code === 'RE' || code === 'AK') {
    return (
      <span className="cell-icon-wrap" title="物资资源箱/明石商店 (RE/AK)">
        <Package size={13} className="cell-icon" />
      </span>
    )
  }
  if (code === 'AM' || code === 'MA') {
    return (
      <span className="cell-icon-wrap" title="弹药补给点 (AM)">
        <Zap size={13} className="cell-icon" />
      </span>
    )
  }
  if (code === 'MI') {
    return (
      <span className="cell-icon-wrap" title="导弹支援点 (MI)">
        <Crosshair size={13} className="cell-icon" />
      </span>
    )
  }

  if (code === '..') {
    return <span className="cell-blind-dots">··</span>
  }

  return <span>{code}</span>
}

// 专用卡片组件集

/** 全局海图网格卡片：列头 + 行号表格，格子按 CELL_DICT 语义着色，附图例。 */
export const MapGridCard = memo(
  function MapGridCard({ card }: { card: Extract<CardItem, { type: 'map_grid' }> }) {
    const [expanded, setExpanded] = useState(true)
    const shapeStr = `${card.cols.length}×${card.rows.length}`

    return (
      <div className="log-card map-card">
        <div className="card-header" onClick={() => setExpanded(!expanded)}>
          <div className="card-title">
            <MapIcon size={16} className="text-accent" />
            <span className="title-bold">海域战术地图快照</span>
            <span className="badge-shape">{shapeStr}</span>
            <span className="card-time">{card.time}</span>
          </div>
          <div className="card-actions">
            <CopyButton text={card.rawText} label="复制矩阵" />
            <button className="card-btn-icon" aria-label="展开或折叠">
              {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
          </div>
        </div>

        {expanded && (
          <div className="card-body">
            <div className="map-grid-viewport">
              <table className="map-ascii-table">
                <thead>
                  <tr>
                    <th className="map-th-corner">#</th>
                    {card.cols.map((col, idx) => (
                      <th key={idx} className="map-th-col">{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {card.rows.map((row) => (
                    <tr key={row.rowNum}>
                      <td className="map-td-row">{row.rowNum}</td>
                      {row.cells.map((cell, cIdx) => {
                        const meta = getCellMeta(cell)
                        return (
                          <td key={cIdx} className="map-td-cell">
                            <span
                              className={`map-badge ${meta.cls}`}
                              title={`[${card.cols[cIdx]}${row.rowNum}] ${meta.label}`}
                            >
                              {renderCellContent(cell)}
                            </span>
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="map-legend-bar">
              <span className="legend-item"><Ship size={12} className="legend-icon text-fleet" /> 旗舰 (FL)</span>
              <span className="legend-item"><Crown size={12} className="legend-icon text-boss" /> Boss (BO)</span>
              <span className="legend-item"><Swords size={12} className="legend-icon text-enemy" /> 敌舰 (1M/EN)</span>
              <span className="legend-item"><Package size={12} className="legend-icon text-mystery" /> 物资/箱 (MY/RE)</span>
              <span className="legend-item"><PawPrint size={12} className="legend-icon text-meowfficer" /> 指挥喵 (ME)</span>
              <span className="legend-item"><AlertCircle size={12} className="legend-icon text-event" /> 事件 (EX)</span>
              <span className="legend-item"><Radar size={12} className="legend-icon text-device" /> 装置 (SD)</span>
              <span className="legend-item"><Ban size={12} className="legend-icon text-impassable" /> 不可走 (++)</span>
              <span className="legend-item"><span className="legend-dot dot-sea" /> 海域 (--)</span>
            </div>
          </div>
        )}
      </div>
    )
  },
  (prev, next) => prev.card === next.card
)

/** 海域透视卡片：SVG 梯形示意四条边界的完整度，附水平/垂直识别指标。 */
export const PerspectiveCard = memo(
  function PerspectiveCard({ card }: { card: Extract<CardItem, { type: 'perspective' }> }) {
    const allActive = card.leftEdge && card.upperEdge && card.rightEdge && card.lowerEdge

    return (
      <div className={`log-card perspective-card ${allActive ? 'perspective-complete' : 'perspective-has-missing'}`}>
        <div className="card-header">
          <div className="card-title">
            <Compass size={16} className={allActive ? 'text-secondary' : 'text-warning'} />
            <span className="title-bold">海域{card.model}与边界线拓扑</span>
            <span className="badge-pill duration">{card.duration}</span>
            <span className="card-time">{card.time}</span>
          </div>
          <div className="card-actions">
            <CopyButton text={card.rawText} />
          </div>
        </div>
        <div className="card-body perspective-body">
          {/* 梯形视口微型几何模型（向前倾斜，近大远小） */}
          <div className="trapezoid-visual" title="海域 2.5D 透视边界视口 (向前倾斜)">
            <svg width="156" height="80" viewBox="0 0 156 80" className="trapezoid-svg">
              {/* 梯形底面浅色半透明背景（仅完全闭合时填充） */}
              <polygon
                points="44,14 112,14 144,68 12,68"
                className={`trapezoid-fill ${allActive ? 'fill-all' : 'fill-broken'}`}
              />
              {/* 纵深透视虚线网格（向前方地平线收拢） */}
              <line x1="60" y1="14" x2="48" y2="68" className="grid-depth-line" />
              <line x1="78" y1="14" x2="78" y2="68" className="grid-depth-line" />
              <line x1="96" y1="14" x2="108" y2="68" className="grid-depth-line" />
              <line x1="28" y1="41" x2="128" y2="41" className="grid-depth-line" />

              {/* 上边界（远处，较短） */}
              <line
                x1="44" y1="14" x2="112" y2="14"
                className={`edge-stroke ${card.upperEdge ? 'edge-active' : 'edge-missing'}`}
              />

              {/* 下边界（近处，较宽） */}
              <line
                x1="12" y1="68" x2="144" y2="68"
                className={`edge-stroke ${card.lowerEdge ? 'edge-active' : 'edge-missing'}`}
              />

              {/* 左边界（向前倾斜收拢） */}
              <line
                x1="12" y1="68" x2="44" y2="14"
                className={`edge-stroke ${card.leftEdge ? 'edge-active' : 'edge-missing'}`}
              />

              {/* 右边界（向前倾斜收拢） */}
              <line
                x1="112" y1="14" x2="144" y2="68"
                className={`edge-stroke ${card.rightEdge ? 'edge-active' : 'edge-missing'}`}
              />
            </svg>
          </div>

          {/* 识别指标清单 */}
          <div className="perspective-metrics">
            <div className="metric-row">
              <span className="metric-label">水平状态:</span>
              <span className="metric-val">{card.info1}</span>
            </div>
            <div className="metric-row">
              <span className="metric-label">垂直/定位:</span>
              <span className="metric-val">{card.info2}</span>
            </div>
          </div>
        </div>
      </div>
    )
  },
  (prev, next) => prev.card === next.card
)

/** 属性清单卡片：连续的 key: value 行排成两列网格。 */
export const PropertySheetCard = memo(
  function PropertySheetCard({ card, search }: { card: Extract<CardItem, { type: 'property_sheet' }>; search: string }) {
    return (
      <div className="log-card property-card">
        <div className="card-header">
          <div className="card-title">
            <Layers size={15} className="text-muted" />
            <span className="title-bold">状态属性清单</span>
            <span className="card-time">{card.time}</span>
          </div>
          <div className="card-actions">
            <CopyButton text={card.rawText} />
          </div>
        </div>
        <div className="card-body">
          <div className="property-grid">
            {card.items.map((item, idx) => (
              <div key={idx} className="property-row">
                <span className="prop-key">{item.key}</span>
                <span className="prop-divider">:</span>
                <span className="prop-val">{renderTokens(item.value, search)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    )
  },
  (prev, next) => prev.card === next.card && prev.search === next.search
)

function renderTableCell(cell: string): ReactNode {
  const trimmed = cell.trim()
  if (trimmed === 'PASS' || trimmed === 'Fastest') {
    return <span style={{ color: '#22c55e', fontWeight: 600 }}>{cell}</span>
  }
  if (trimmed === 'Warning' || trimmed === 'Medium') {
    return <span style={{ color: '#eab308', fontWeight: 600 }}>{cell}</span>
  }
  if (trimmed === 'Failed' || trimmed === 'Error' || trimmed === 'Slow') {
    return <span style={{ color: '#ef4444', fontWeight: 600 }}>{cell}</span>
  }
  if (trimmed === 'T0') {
    return <span style={{ color: '#f59e0b', fontWeight: 700 }}>{cell}</span>
  }
  if (trimmed === 'T1') {
    return <span style={{ color: '#8b5cf6', fontWeight: 600 }}>{cell}</span>
  }
  return cell
}

/** 数据表格卡片：Rich/ASCII 表格还原成原生表格，列对齐按数字占比推断。 */
export const DataTableCard = memo(
  function DataTableCard({ card }: { card: Extract<CardItem, { type: 'data_table' }> }) {
    // 智能推断列对齐方式：若该列非空值多为数字或测量单位，则右对齐，否则左对齐。
    const colAlignments = useMemo(() => {
      return card.headers.map((_, cIdx) => {
        let numericCount = 0
        let totalCount = 0
        for (const row of card.rows) {
          const val = row[cIdx]?.trim() || ''
          if (val) {
            totalCount++
            if (/^[-+]?[\d.,]+([a-zA-Z%]+|\/[0-9]+)?$/.test(val)) {
              numericCount++
            }
          }
        }
        return totalCount > 0 && numericCount / totalCount >= 0.6 ? 'right' : 'left'
      })
    }, [card.headers, card.rows])

    return (
      <div className="log-card table-card">
        <div className="card-header table-card-header">
          <div className="card-title">
            <TableIcon size={14} className="text-accent" />
            <span className="title-bold">{card.title}</span>
            <span className="card-time">{card.time}</span>
          </div>
          <div className="card-actions">
            <CopyButton text={card.rawText} />
          </div>
        </div>
        <div className="card-body table-card-body">
          <div className="data-table-viewport">
            <table className="native-log-table">
              <thead>
                <tr>
                  {card.headers.map((h, i) => (
                    <th key={i} style={{ textAlign: colAlignments[i] }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {card.rows.map((row, rIdx) => (
                  <tr key={rIdx}>
                    {row.map((cell, cIdx) => (
                      <td key={cIdx} style={{ textAlign: colAlignments[cIdx] }}>
                        {renderTableCell(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    )
  },
  (prev, next) => prev.card === next.card
)

// 异常堆栈解析与结构化渲染

interface StackCodeLine {
  lineNum: number
  isFault: boolean
  code: string
}

interface StackLocalVar {
  name: string
  value: string
}

interface ParsedStackFrame {
  file: string
  fileName: string
  line: number
  func: string
  codeLines: StackCodeLine[]
  locals: StackLocalVar[]
}

interface ParsedTraceback {
  frames: ParsedStackFrame[]
  excLine: string
  rawText: string
}

function normalizeCodeLines(codeLines: StackCodeLine[]): StackCodeLine[] {
  const cleaned = codeLines.map(c => ({ ...c, code: c.code.replace(/│/g, ' ') }))
  let minIndent = Infinity
  for (const c of cleaned) {
    if (!c.code.trim()) continue
    const match = c.code.match(/^\s*/)
    const indent = match ? match[0].length : 0
    if (indent < minIndent) minIndent = indent
  }
  if (minIndent > 0 && minIndent !== Infinity) {
    for (const c of cleaned) {
      c.code = c.code.trim() ? c.code.slice(minIndent) : ''
    }
  }
  return cleaned
}

function parseTraceback(raw: string): ParsedTraceback {
  const lines = raw.split('\n').map(l => l.replace(/^\s{4,10}/, '').trimEnd())
  let currentFrame: ParsedStackFrame | null = null
  const frames: ParsedStackFrame[] = []
  let excLine = ''
  let inLocals = false
  let currentLocals: StackLocalVar[] = []

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i]
    const stripped = rawLine.replace(/^[│\s]+|[│\s]+$/g, '').trim()

    // 检查最后的异常类型与说明：ScriptEnd: ... 或 FooError: ...。
    const excMatch = rawLine.match(/^([a-zA-Z0-9_.]*(?:Error|Exception|Exit|Interrupt|ScriptEnd))(?::\s*(.*))?$/)
    if (excMatch && excMatch[1] && !rawLine.includes('Traceback') && !rawLine.includes('File ')) {
      excLine = rawLine.trim()
      continue
    }

    // 匹配调用栈帧头部：
    // 1. Rich 风格：E:\AzurPilot\alas.py:1019 in run
    const richFrame = rawLine.match(/[│]?\s*([a-zA-Z]:[\\\/][^:]+):(\d+)\s+in\s+([^\s│]+)/)
    // 2. Python 标准风格：File "E:\AzurPilot\alas.py", line 1019, in run
    const stdFrame = rawLine.match(/File\s+["\x27]([^"\x27]+)["\x27],\s+line\s+(\d+)(?:,\s+in\s+([^\s│]+))?/)

    const frameMatch = richFrame || stdFrame
    if (frameMatch) {
      if (currentFrame) {
        if (currentLocals.length) currentFrame.locals = currentLocals
        currentFrame.codeLines = normalizeCodeLines(currentFrame.codeLines)
        frames.push(currentFrame)
      }
      currentLocals = []
      inLocals = false
      const fullPath = frameMatch[1].trim()
      const fileName = fullPath.split(/[\\\/]/).pop() || fullPath
      currentFrame = {
        file: fullPath,
        fileName,
        line: parseInt(frameMatch[2], 10),
        func: (frameMatch[3] || '<module>').trim(),
        codeLines: [],
        locals: [],
      }
      continue
    }

    if (!currentFrame) continue

    // 匹配 locals 变量框。
    if (rawLine.includes('locals') && rawLine.includes('─')) {
      inLocals = true
      continue
    }
    if (inLocals) {
      if (rawLine.includes('╰') || (rawLine.includes('─') && rawLine.includes('╯'))) {
        inLocals = false
        continue
      }
      const localMatch = rawLine.match(/[│]?\s*([a-zA-Z0-9_]+)\s*=\s*(.*?)\s*[│]?$/)
      if (localMatch && localMatch[1] !== 'locals') {
        currentLocals.push({ name: localMatch[1], value: localMatch[2].replace(/\s*│$/, '').trim() })
      }
      continue
    }

    // 匹配 Rich 代码行（含行号、故障标记 ❱/▶/> 与代码）。
    const richCodeMatch = rawLine.match(/[│]?\s*(❱|▶|>)?\s*(\d+)\s*│\s*(.*?)\s*[│]?$/)
    if (richCodeMatch) {
      const isFault = Boolean(richCodeMatch[1])
      const lineNum = parseInt(richCodeMatch[2], 10)
      const code = richCodeMatch[3].replace(/[│\s]+$/, '')
      currentFrame.codeLines.push({ lineNum, isFault, code })
      continue
    }

    // 标准 Python 单行代码追踪（紧随 File 行之后）。
    if (stripped && !rawLine.includes('Traceback') && !rawLine.includes('╭') && !rawLine.includes('╰')) {
      if (currentFrame.codeLines.length === 0) {
        currentFrame.codeLines.push({ lineNum: currentFrame.line, isFault: true, code: stripped })
      }
    }
  }

  if (currentFrame) {
    if (currentLocals.length) currentFrame.locals = currentLocals
    currentFrame.codeLines = normalizeCodeLines(currentFrame.codeLines)
    frames.push(currentFrame)
  }

  return { frames, excLine, rawText: raw }
}

/** Traceback 渲染器：解析 Rich/标准两种栈帧格式，结构化视图与原始文本可切换。 */
const TracebackViewer = memo(
  function TracebackViewer({ rawText }: { rawText: string }) {
    const [viewMode, setViewMode] = useState<'structured' | 'raw'>('structured')
    const parsed = useMemo(() => parseTraceback(rawText), [rawText])

    const cleanedRaw = useMemo(() => {
      return rawText.replace(/^\s{4,10}/gm, '')
    }, [rawText])

    if (parsed.frames.length === 0 || viewMode === 'raw') {
      return (
        <div className="traceback-viewer">
          <div className="traceback-toolbar">
            <div className="traceback-tool-info">
              <Terminal size={14} className="text-danger" />
              <span className="traceback-tool-title">Python 异常堆栈追踪 (Traceback)</span>
              {parsed.frames.length > 0 && (
                <span className="badge-pill duration">{parsed.frames.length} 个栈帧</span>
              )}
            </div>
            <div className="traceback-tool-actions">
              {parsed.frames.length > 0 && (
                <button
                  type="button"
                  className="card-btn-action"
                  onClick={() => setViewMode('structured')}
                >
                  查看结构化视图
                </button>
              )}
              <CopyButton text={cleanedRaw} label="复制堆栈" />
            </div>
          </div>
          <pre className="traceback-raw-pre">{cleanedRaw}</pre>
        </div>
      )
    }

    return (
      <div className="traceback-viewer">
        <div className="traceback-toolbar">
          <div className="traceback-tool-info">
            <Terminal size={14} className="text-danger" />
            <span className="traceback-tool-title">Python 异常堆栈追踪 (Traceback)</span>
            <span className="badge-pill duration">{parsed.frames.length} 个栈帧</span>
          </div>
          <div className="traceback-tool-actions">
            <button
              type="button"
              className="card-btn-action"
              onClick={() => setViewMode('raw')}
            >
              查看原始文本
            </button>
            <CopyButton text={cleanedRaw} label="复制堆栈" />
          </div>
        </div>

        <div className="traceback-frames-list">
          {parsed.frames.map((frame, idx) => (
            <div key={idx} className="traceback-frame-card">
              <div className="traceback-frame-header">
                <div className="frame-header-left">
                  <span className="frame-filename">{frame.fileName}</span>
                  <span className="frame-line-badge">:{frame.line}</span>
                  <span className="frame-func">in <span className="func-name">{frame.func}()</span></span>
                </div>
                <span className="frame-filepath" title={frame.file}>{frame.file}</span>
              </div>

              {frame.codeLines.length > 0 && (
                <div className="traceback-code-block">
                  {frame.codeLines.map((line, lIdx) => (
                    <div
                      key={lIdx}
                      className={`traceback-code-row ${line.isFault ? 'fault-row' : ''}`}
                    >
                      <div className="gutter-col">
                        {line.isFault ? (
                          <span className="fault-marker">▶</span>
                        ) : (
                          <span className="gutter-spacer" />
                        )}
                        <span className="line-num">{line.lineNum}</span>
                      </div>
                      <div className="code-col">
                        <span className="code-text">{line.code}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {frame.locals.length > 0 && (
                <div className="traceback-locals-block">
                  <div className="locals-title">局部变量 (locals)</div>
                  <div className="locals-list">
                    {frame.locals.map((v, vIdx) => (
                      <div key={vIdx} className="local-var-row">
                        <span className="local-key">{v.name}</span>
                        <span className="local-eq">=</span>
                        <span className="local-val">{v.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>

        {parsed.excLine && (
          <div className="traceback-exc-banner">
            <AlertCircle size={15} className="text-danger flex-shrink-0" />
            <span className="exc-banner-text">{parsed.excLine}</span>
          </div>
        )}
      </div>
    )
  },
  (prev, next) => prev.rawText === next.rawText
)

/** 统一错误上下文卡片：原因/影响/建议/底层异常分段展开，内嵌堆栈查看器。 */
export const ErrorContextCard = memo(
  function ErrorContextCard({ card }: { card: Extract<CardItem, { type: 'error_context' }> }) {
    return (
      <div className="log-card error-card">
        <div className="card-header error-header">
          <div className="card-title">
            <AlertCircle size={18} className="text-danger" />
            <span className="title-bold error-title">{card.title}</span>
            <span className="card-time">{card.time}</span>
          </div>
          <div className="card-actions">
            <CopyButton text={card.rawText} label="复制错误现场" />
          </div>
        </div>

        <div className="card-body error-body">
          {card.reason && (
            <div className="error-section">
              <span className="error-tag tag-reason">原因</span>
              <span className="error-text">{card.reason}</span>
            </div>
          )}
          {card.impact && (
            <div className="error-section">
              <span className="error-tag tag-impact">影响</span>
              <span className="error-text">{card.impact}</span>
            </div>
          )}
          {card.action && (
            <div className="error-section section-action">
              <span className="error-tag tag-action">建议操作</span>
              <span className="error-text text-action">{card.action}</span>
            </div>
          )}
          {card.exception && (
            <div className="error-section">
              <span className="error-tag tag-exc">底层异常</span>
              <span className="error-text text-mono text-muted">{card.exception}</span>
            </div>
          )}

          {card.stackTrace && (
            <div className="error-stack-wrapper">
              <TracebackViewer rawText={card.stackTrace} />
            </div>
          )}
        </div>
      </div>
    )
  },
  (prev, next) => prev.card === next.card
)

/** 异常堆栈卡片：整段 Traceback 交给 TracebackViewer 渲染。 */
export const TracebackCard = memo(
  function TracebackCard({ card }: { card: Extract<CardItem, { type: 'traceback' }> }) {
    return (
      <div className="log-card traceback-card">
        <div className="card-header">
          <div className="card-title">
            <Terminal size={15} className="text-warning" />
            <span className="title-bold">{card.excName}</span>
            <span className="card-time">{card.time}</span>
          </div>
          <div className="card-actions">
            <CopyButton text={card.rawText} label="复制堆栈" />
          </div>
        </div>
        <div className="card-body">
          <TracebackViewer rawText={card.rawText} />
        </div>
      </div>
    )
  },
  (prev, next) => prev.card === next.card
)

/** LLM 分析报告卡片：Markdown 渲染报告正文，徽章显示模型名。 */
export const LlmReportCard = memo(
  function LlmReportCard({ card }: { card: Extract<CardItem, { type: 'llm_report' }> }) {
    return (
      <div className="log-card llm-card">
        <div className="card-header llm-header">
          <div className="card-title">
            <Sparkles size={16} className="text-llm" />
            <span className="title-bold">AI 错误智能分析诊断报告</span>
            <span className="badge-pill llm-model">{card.model}</span>
            <span className="card-time">{card.time}</span>
          </div>
          <div className="card-actions">
            <CopyButton text={card.content} label="复制报告" />
          </div>
        </div>
        <div className="card-body">
          <LazyMarkdown content={card.content} className="llm-markdown-view" />
        </div>
      </div>
    )
  },
  (prev, next) => prev.card === next.card
)

/** 矩阵切片卡片：局部视野/雷达扫描的两字符单元格矩阵。 */
export const MatrixGridCard = memo(
  function MatrixGridCard({ card }: { card: Extract<CardItem, { type: 'matrix_grid' }> }) {
    const [open, setOpen] = useState(true)

    return (
      <div className="log-card matrix-card">
        <div className="card-header" onClick={() => setOpen(!open)}>
          <div className="card-title">
            <MapIcon size={15} className="text-secondary" />
            <span className="title-bold">{card.title}</span>
            <span className="card-time">{card.time}</span>
          </div>
          <div className="card-actions">
            <CopyButton text={card.rawText} />
            <button className="card-btn-icon" aria-label="展开或折叠">
              {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
          </div>
        </div>
        {open && (
          <div className="card-body">
            <div className="map-grid-viewport">
              <div className="matrix-grid-rows">
                {card.rows.map((row, rIdx) => (
                  <div key={rIdx} className="matrix-row">
                    {row.map((cell, cIdx) => {
                      const meta = getCellMeta(cell)
                      return (
                        <span key={cIdx} className={`map-badge ${meta.cls}`} title={meta.label}>
                          {renderCellContent(cell)}
                        </span>
                      )
                    })}
                  </div>
                ))}
              </div>
            </div>

            <div className="map-legend-bar">
              <span className="legend-item"><Ship size={12} className="legend-icon text-fleet" /> 旗舰 (FL)</span>
              <span className="legend-item"><Crown size={12} className="legend-icon text-boss" /> Boss (BO)</span>
              <span className="legend-item"><Swords size={12} className="legend-icon text-enemy" /> 敌舰 (1M/EN)</span>
              <span className="legend-item"><Package size={12} className="legend-icon text-mystery" /> 物资/箱 (MY/RE)</span>
              <span className="legend-item"><PawPrint size={12} className="legend-icon text-meowfficer" /> 指挥喵 (ME)</span>
              <span className="legend-item"><AlertCircle size={12} className="legend-icon text-event" /> 事件 (EX)</span>
              <span className="legend-item"><Radar size={12} className="legend-icon text-device" /> 装置 (SD)</span>
              <span className="legend-item"><Ban size={12} className="legend-icon text-impassable" /> 不可走 (++)</span>
              <span className="legend-item"><span className="legend-dot dot-sea" /> 海域 (--)</span>
            </div>
          </div>
        )}
      </div>
    )
  },
  (prev, next) => prev.card === next.card
)

function interpolateColor(
  c1: [number, number, number],
  c2: [number, number, number],
  factor: number
): string {
  const r = Math.round(c1[0] + factor * (c2[0] - c1[0]))
  const g = Math.round(c1[1] + factor * (c2[1] - c1[1]))
  const b = Math.round(c1[2] + factor * (c2[2] - c1[2]))
  return `rgb(${r}, ${g}, ${b})`
}

/** 热力渐变停靠点：t ∈ [0,1] 由代价值归一而来，按远近插值取色。 */
const HEATMAP_STOPS: [number, [number, number, number]][] = [
  [0.0, [2, 132, 199]],   // #0284c7 Sky Blue（近距代价 1）
  [0.25, [37, 99, 235]],  // #2563eb 蓝色调
  [0.5, [124, 58, 237]],  // #7c3aed 紫色调
  [0.75, [192, 38, 211]], // #c026d3 品红色调
  [1.0, [225, 29, 72]],   // #e11d48 Rose（远距最高代价）
]

/** 代价格子的配色：0 是起点绿，≥9000 是不可达暗格，其余按 maxCost 归一到渐变色带。 */
export function getCostHeatmapStyle(num: number, maxCost: number): React.CSSProperties {
  if (num >= 9000) {
    return {
      backgroundColor: '#000000',
      color: '#52525b',
      fontSize: '10px',
    }
  }
  if (num === 0) {
    return {
      backgroundColor: '#10b981',
      color: '#ffffff',
      fontWeight: 700,
    }
  }
  const t = Math.max(0, Math.min(1, maxCost > 1 ? (num - 1) / (maxCost - 1) : 0))
  for (let i = 0; i < HEATMAP_STOPS.length - 1; i++) {
    const [t1, c1] = HEATMAP_STOPS[i]
    const [t2, c2] = HEATMAP_STOPS[i + 1]
    if (t >= t1 && t <= t2) {
      const factor = (t - t1) / (t2 - t1)
      return {
        backgroundColor: interpolateColor(c1, c2, factor),
        color: '#ffffff',
      }
    }
  }
  return {
    backgroundColor: '#0284c7',
    color: '#ffffff',
  }
}

/** 寻路代价热力图卡片：代价格子按 HEATMAP_STOPS 渐变着色，附图例。 */
export const CostGridCard = memo(
  function CostGridCard({ card }: { card: Extract<CardItem, { type: 'cost_grid' }> }) {
    const [open, setOpen] = useState(true)
    const shapeStr = `${card.cols.length}×${card.rows.length}`

    const maxCost = useMemo(() => {
      let max = 1
      for (const row of card.rows) {
        for (const val of row.values) {
          const n = parseInt(val, 10)
          if (!isNaN(n) && n < 9000 && n > max) {
            max = n
          }
        }
      }
      return max
    }, [card.rows])

    return (
      <div className="log-card cost-card">
        <div className="card-header" onClick={() => setOpen(!open)}>
          <div className="card-title">
            <Compass size={15} className="text-accent" />
            <span className="title-bold">寻路移动代价热力图 (Cost Map)</span>
            <span className="badge-shape">{shapeStr}</span>
            <span className="card-time">{card.time}</span>
          </div>
          <div className="card-actions">
            <CopyButton text={card.rawText} label="复制矩阵" />
            <button className="card-btn-icon" aria-label="展开或折叠">
              {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
          </div>
        </div>
        {open && (
          <div className="card-body">
            <div className="map-grid-viewport">
              <table className="map-ascii-table cost-table">
                <thead>
                  <tr>
                    <th className="map-th-corner">#</th>
                    {card.cols.map((col, idx) => (
                      <th key={idx} className="map-th-col">{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {card.rows.map((row) => (
                    <tr key={row.rowNum}>
                      <td className="map-td-row">{row.rowNum}</td>
                      {row.values.map((val, cIdx) => {
                        const num = parseInt(val, 10)
                        const isObstacle = num >= 9000
                        const isOrigin = num === 0
                        const cellStyle = getCostHeatmapStyle(num, maxCost)
                        const title = isObstacle
                          ? '不可达障碍 (9999)'
                          : isOrigin
                          ? '寻路起点 (0 步)'
                          : `移动代价: ${num} 步`

                        return (
                          <td key={cIdx} className="map-td-cell">
                            <span
                              className={`cost-cell ${isObstacle ? 'cost-wall' : isOrigin ? 'cost-origin' : 'cost-path'}`}
                              style={cellStyle}
                              title={title}
                            >
                              {val}
                            </span>
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="map-legend-bar">
              <span className="legend-item"><span className="legend-dot dot-origin" /> 起点 (0)</span>
              <span className="legend-item"><span className="legend-dot dot-cost-low" /> 近距/低代价</span>
              <span className="legend-item"><span className="legend-dot dot-cost-mid" /> 中距代价</span>
              <span className="legend-item"><span className="legend-dot dot-cost-high" /> 远距代价 (最高: {maxCost})</span>
              <span className="legend-item"><span className="legend-dot dot-cost-wall" /> 不可达障碍 (9999)</span>
            </div>
          </div>
        )}
      </div>
    )
  },
  (prev, next) => prev.card === next.card
)

/** 系统横幅卡片：双横线夹标题的全宽横幅。 */
export const SystemBannerCard = memo(
  function SystemBannerCard({ card }: { card: Extract<CardItem, { type: 'system_banner' }> }) {
    return (
      <div className="log-card system-banner-card">
        <div className="banner-double-rule" />
        <div className="banner-title-text">{card.title}</div>
        <div className="banner-double-rule" />
      </div>
    )
  },
  (prev, next) => prev.card === next.card
)

/** 任务阶段标题卡片：横线夹标题，level 区分主/次。 */
export const StageHeaderCard = memo(
  function StageHeaderCard({ card }: { card: Extract<CardItem, { type: 'stage_header' }> }) {
    return (
      <div className={`log-card stage-header-card level-${card.level}`}>
        <div className="stage-rule-bar" />
        <div className="stage-title-wrap">
          <span className="stage-title">{card.title}</span>
          {card.time && <span className="stage-time">{card.time}</span>}
        </div>
        <div className="stage-rule-bar" />
      </div>
    )
  },
  (prev, next) => prev.card === next.card
)

/** 常规单行日志行：级别、时间与正文的高亮渲染。 */
export const SingleLogLineCard = memo(
  function SingleLogLineCard({ card, search }: { card: Extract<CardItem, { type: 'single' }>; search: string }) {
    const lvlKey = card.level.toLowerCase()
    return (
      <div className={`log-line log-entry-line level-${lvlKey} log-card-line`}>
        <span className={`log-lvl lvl-${lvlKey}`}>{card.level}</span>
        <span className="log-ts">{card.time}</span>
        <span className="log-divider">│</span>
        <span className="log-msg">{renderTokens(card.message, search)}</span>
      </div>
    )
  },
  (prev, next) => prev.card === next.card && prev.search === next.search
)

// 虚拟化窗口与卡片高度预估

/** 卡片数达到该阈值才启用虚拟化窗口；更少时全量渲染开销更低。 */
export const VIRTUAL_THRESHOLD = 40
/** 虚拟窗口上下各多渲染的像素余量，减少快速滚动时的白屏。 */
export const OVERSCAN_BUFFER_PX = 800
const CARD_GAP_PX = 8

/** 滚动不足半段预渲染余量时复用当前窗口，减少视口边缘的挂载与卸载。 */
export function logWindowTop(scrollTop: number) {
  const step = OVERSCAN_BUFFER_PX / 2
  return Math.floor(scrollTop / step) * step
}

/** requestAnimationFrame 的环境兜底：无 window（测试/SSR）时退化为 16ms 的 setTimeout。 */
export const safeRaf = (cb: FrameRequestCallback): number => {
  if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
    return window.requestAnimationFrame(cb)
  }
  return setTimeout(cb, 16) as unknown as number
}

/** 与 safeRaf 配对取消；id 为 null 时忽略。 */
export const safeCancelRaf = (id: number | null) => {
  if (id === null) return
  if (typeof window !== 'undefined' && typeof window.cancelAnimationFrame === 'function') {
    window.cancelAnimationFrame(id)
  } else {
    clearTimeout(id)
  }
}

/**
 * 依据卡片类型与内部数据结构预估卡片渲染高度（包含 CSS padding/border 等）。
 */
export function getCardEstimatedHeight(card: CardItem): number {
  switch (card.type) {
    case 'single':
      return 34
    case 'stage_header':
      return 44
    case 'system_banner':
      return 74
    case 'perspective':
      return 172
    case 'map_grid':
      return Math.max(120, 52 + card.rows.length * 28 + 48)
    case 'cost_grid':
      return Math.max(120, 52 + card.rows.length * 28 + 48)
    case 'matrix_grid':
      return Math.max(100, 52 + card.rows.length * 24 + 48)
    case 'property_sheet':
      return Math.max(70, 48 + card.items.length * 26)
    case 'data_table':
      return Math.max(90, 48 + card.rows.length * 28 + 36)
    case 'error_context':
      return 280
    case 'traceback':
      return 220
    case 'llm_report':
      return 260
    default:
      return 34
  }
}

/**
 * 二分查找当前视口区域 [visibleTop, visibleBottom] 所覆盖的卡片索引范围 [startIndex, endIndex]。
 */
export function findVisibleRange(
  offsets: number[],
  heights: number[],
  visibleTop: number,
  visibleBottom: number,
  totalCount: number
): [number, number] {
  if (totalCount === 0) return [0, 0]

  // 若视口顶部已经超出全部卡片总底部，直接锁定末尾卡片。
  const lastBottom = (offsets[totalCount - 1] ?? 0) + (heights[totalCount - 1] ?? 0)
  if (visibleTop >= lastBottom) {
    return [totalCount - 1, totalCount - 1]
  }

  // 若视口底部小于等于 0，直接锁定第一张卡片。
  if (visibleBottom <= 0) {
    return [0, 0]
  }

  // 二分查找满足 offsets[i] + heights[i] >= visibleTop 的最小 i（startIndex）。
  let low = 0
  let high = totalCount - 1
  let startIndex = 0

  while (low <= high) {
    const mid = (low + high) >> 1
    const itemBottom = offsets[mid] + heights[mid]
    if (itemBottom >= visibleTop) {
      startIndex = mid
      high = mid - 1
    } else {
      low = mid + 1
    }
  }

  // 二分查找满足 offsets[i] <= visibleBottom 的最大 i（endIndex）。
  low = startIndex
  high = totalCount - 1
  let endIndex = startIndex

  while (low <= high) {
    const mid = (low + high) >> 1
    if (offsets[mid] <= visibleBottom) {
      endIndex = mid
      low = mid + 1
    } else {
      high = mid - 1
    }
  }

  return [Math.max(0, startIndex), Math.min(totalCount - 1, Math.max(startIndex, endIndex))]
}

/**
 * 单个卡片类型分发渲染。
 */
function renderCardItem(card: CardItem, search: string): ReactNode {
  switch (card.type) {
    case 'map_grid':
      return <MapGridCard key={card.id} card={card} />
    case 'perspective':
      return <PerspectiveCard key={card.id} card={card} />
    case 'cost_grid':
      return <CostGridCard key={card.id} card={card} />
    case 'matrix_grid':
      return <MatrixGridCard key={card.id} card={card} />
    case 'property_sheet':
      return <PropertySheetCard key={card.id} card={card} search={search} />
    case 'data_table':
      return <DataTableCard key={card.id} card={card} />
    case 'error_context':
      return <ErrorContextCard key={card.id} card={card} />
    case 'traceback':
      return <TracebackCard key={card.id} card={card} />
    case 'llm_report':
      return <LlmReportCard key={card.id} card={card} />
    case 'system_banner':
      return <SystemBannerCard key={card.id} card={card} />
    case 'stage_header':
      return <StageHeaderCard key={card.id} card={card} />
    case 'single':
    default:
      return <SingleLogLineCard key={card.id} card={card} search={search} />
  }
}

interface LogCardViewProps {
  entries: LogEntry[]
  search: string
  scrollRef?: RefObject<HTMLDivElement | null>
}

/**
 * 日志卡片流主组件：先把日志聚合成卡片，少于阈值全量渲染，达到阈值走虚拟窗口
 * （估算高度占位，ResizeObserver 实测修正，滚动位置二分定位可见区间）。
 *
 * @param search 搜索词，命中片段以 <mark> 高亮。
 * @param scrollRef 外层滚动容器引用；不传时回退到组件的最近父元素。
 */
export const LogCardView = memo(function LogCardView({
  entries,
  search,
  scrollRef,
}: LogCardViewProps) {
  const cards = useMemo(() => aggregateEntriesToCards(entries), [entries])
  const containerRef = useRef<HTMLDivElement>(null)
  const isVirtual = cards.length >= VIRTUAL_THRESHOLD

  // 动态测量的高度缓存（按 card.id 记录实际渲染高度）。
  const heightCacheRef = useRef<Map<number, number>>(new Map())
  const [measureVersion, setMeasureVersion] = useState(0)
  const measureRafRef = useRef<number | null>(null)

  // 高度变化合并到一帧再重渲染：ResizeObserver 高频触发，逐次 setState 会拖垮滚动。
  const requestMeasureUpdate = useCallback(() => {
    if (measureRafRef.current !== null) return
    measureRafRef.current = safeRaf(() => {
      measureRafRef.current = null
      setMeasureVersion(v => v + 1)
    })
  }, [])

  const [scrollState, setScrollState] = useState({ scrollTop: 0, clientHeight: 800 })

  // 获取外层滚动容器（优先传入的 scrollRef，其次找最近父级）。
  const getScrollElement = useCallback(() => {
    return scrollRef?.current ?? containerRef.current?.parentElement ?? null
  }, [scrollRef])

  // 监听外部滚动容器的滚动与尺寸变化。
  useEffect(() => {
    if (!isVirtual) return
    const scrollEl = getScrollElement()
    if (!scrollEl) return

    const syncWindow = () => {
      const scrollTop = logWindowTop(scrollEl.scrollTop)
      const clientHeight = scrollEl.clientHeight || 800
      setScrollState(previous => previous.scrollTop === scrollTop && previous.clientHeight === clientHeight
        ? previous : {scrollTop, clientHeight})
    }
    syncWindow()

    let scrollRafId: number | null = null
    const onScroll = () => {
      if (scrollRafId !== null) return
      scrollRafId = safeRaf(() => {
        scrollRafId = null
        syncWindow()
      })
    }

    scrollEl.addEventListener('scroll', onScroll, { passive: true })

    let resizeObserver: ResizeObserver | null = null
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(syncWindow)
      resizeObserver.observe(scrollEl)
    }

    return () => {
      scrollEl.removeEventListener('scroll', onScroll)
      if (scrollRafId !== null) safeCancelRaf(scrollRafId)
      resizeObserver?.disconnect()
    }
  }, [getScrollElement, isVirtual])

  // ResizeObserver 观察可见卡片的实际高度变动（折叠/展开/动态排版都会改变占位）。
  const cardObserverRef = useRef<ResizeObserver | null>(null)
  const cardNodes = useRef(new Set<HTMLDivElement>())
  useLayoutEffect(() => {
    if (!isVirtual || typeof ResizeObserver === 'undefined') return

    const observer = new ResizeObserver((observerEntries) => {
      let changed = false
      for (const entry of observerEntries) {
        const el = entry.target as HTMLElement
        const idAttr = el.getAttribute('data-card-id')
        if (!idAttr) continue
        const cardId = parseInt(idAttr, 10)
        const measured = entry.borderBoxSize?.[0]?.blockSize ?? entry.contentRect.height
        if (measured > 0) {
          // 变化不足 2px 当作测量抖动忽略，避免亚像素差异反复触发重排。
          const prev = heightCacheRef.current.get(cardId)
          if (prev === undefined || Math.abs(prev - measured) >= 2) {
            heightCacheRef.current.set(cardId, measured)
            changed = true
          }
        }
      }
      if (changed) {
        requestMeasureUpdate()
      }
    })
    cardObserverRef.current = observer
    for (const node of cardNodes.current) observer.observe(node)

    return () => {
      observer.disconnect()
      cardObserverRef.current = null
      if (measureRafRef.current !== null) {
        safeCancelRaf(measureRafRef.current)
        measureRafRef.current = null
      }
    }
  }, [isVirtual, requestMeasureUpdate])

  const registerCardRef = useCallback((node: HTMLDivElement | null) => {
    if (!node) return
    const nodes = cardNodes.current
    nodes.add(node)
    cardObserverRef.current?.observe(node)
    return () => {
      nodes.delete(node)
      cardObserverRef.current?.unobserve(node)
    }
  }, [])

  // 测量结果最多保留当前一屏历史窗口的数量级，连续运行也不会累积旧日志行高。
  useEffect(() => {
    const measured = heightCacheRef.current
    if (measured.size <= 2 * cards.length) return
    const retained = new Set(cards.map(card => card.id))
    for (const id of measured.keys()) {
      if (!retained.has(id)) measured.delete(id)
    }
  }, [cards])

  // 滚动只移动窗口，偏移表仅在卡片或实测高度变化后重算。
  const {heights, offsets, totalHeight} = useMemo(() => {
    const heights: number[] = []
    const offsets: number[] = []
    let height = 0
    if (isVirtual) {
      for (const card of cards) {
        const rowHeight = (heightCacheRef.current.get(card.id) ?? getCardEstimatedHeight(card)) + CARD_GAP_PX
        heights.push(rowHeight)
        offsets.push(height)
        height += rowHeight
      }
    }
    return {heights, offsets, totalHeight: Math.max(0, height - CARD_GAP_PX)}
  }, [cards, isVirtual, measureVersion])

  // 卡片不多时直接全量渲染，省去窗口计算与测量开销。
  if (!isVirtual) {
    return (
      <div ref={containerRef} className="log-cards-container">
        {cards.map((card) => renderCardItem(card, search))}
      </div>
    )
  }

  const totalCount = cards.length

  const visibleTop = Math.max(0, scrollState.scrollTop - OVERSCAN_BUFFER_PX)
  const visibleBottom = scrollState.scrollTop + scrollState.clientHeight + OVERSCAN_BUFFER_PX

  const [startIndex, endIndex] = findVisibleRange(offsets, heights, visibleTop, visibleBottom, totalCount)
  const paddingTop = offsets[startIndex] ?? 0
  const bottomItemEnd = Math.max(0, (offsets[endIndex] ?? 0) + (heights[endIndex] ?? 0) - CARD_GAP_PX)
  const paddingBottom = Math.max(0, totalHeight - bottomItemEnd)

  const visibleCards = cards.slice(startIndex, endIndex + 1)

  return (
    <div
      ref={containerRef}
      className="log-cards-container"
      style={{
        paddingTop: `${paddingTop}px`,
        paddingBottom: `${paddingBottom}px`,
        boxSizing: 'border-box',
      }}
    >
      {visibleCards.map((card) => (
        <div key={card.id} data-card-id={card.id} ref={registerCardRef} className="log-card-virtual-item">
          {renderCardItem(card, search)}
        </div>
      ))}
    </div>
  )
})
