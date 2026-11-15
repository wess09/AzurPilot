/**
 * @fileoverview 日志条目到结构化卡片的流式聚合与增量缓存。
 * 从 LogCardView.tsx 原 188-198、218-819 行提取，纯搬迁未改动。
 */

import type { LogEntry } from '../../api/types'
import { extractLogMessage } from './tokens'

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
export function aggregateSlice(
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
    if (!entry) break
    const raw = entry.text.replace(/[\r\n]+$/, '')
    const { level, time, message } = extractLogMessage(raw)
    const trimmedMsg = message.trim()

    // 1. 系统级横幅（Level 0 HR：═ + 居中文本 + ═）。
    if (
      trimmedMsg.includes('═'.repeat(10)) &&
      index + 2 < entries.length
    ) {
      const nextEntry1 = entries[index + 1]
      const nextEntry2 = entries[index + 2]
      if (nextEntry1 && nextEntry2) {
      const next1 = extractLogMessage(nextEntry1.text).message.trim()
      const next2 = extractLogMessage(nextEntry2.text).message.trim()
      if (next2.includes('═'.repeat(10)) && next1 && !next1.includes('═')) {
        const card: CardItem = {
          type: 'system_banner',
          id: entry.id,
          time,
          title: next1,
          rawText: [entry.text, nextEntry1.text, nextEntry2.text].join('\n'),
        }
        index += 3
        cards.push(card)
        ranges.push({ card, start: cardStart, end: index })
        continue
      }
      }
    }

    // 2. 任务/阶段带线标题（Level 1/2 HR：═ TITLE ═ + 紧随其后的同名 INFO）。
    const ruleMatch = /^[═─]{3,}\s*(.*?)\s*[═─]{3,}$/.exec(trimmedMsg)
    const ruleTitle = ruleMatch?.[1]?.trim()
    if (ruleMatch && ruleTitle) {
      const title = ruleTitle
      const isDouble = trimmedMsg.includes('═')
      // 检查下一行是否重复输出了同名 INFO。
      let rawText = entry.text
      const nextEntry = entries[index + 1]
      if (nextEntry) {
        const nextMsg = extractLogMessage(nextEntry.text).message.trim()
        if (nextMsg === title) {
          rawText += '\n' + nextEntry.text
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
    const nextPerspectiveEntry = entries[index + 1]
    if (perspMatch && nextPerspectiveEntry) {
      const nextMsg = extractLogMessage(nextPerspectiveEntry.text).message
      const nextPersp = /^\[地图-(透视|单应性)\]\s+边缘:\s*([\/ _\\]*?)\s+(垂直:.*|单应位置:.*)$/.exec(nextMsg.trim())
      const edgesStr = nextPersp?.[2]
      const model = perspMatch[1] === '透视' || perspMatch[1] === '单应性' ? perspMatch[1] : undefined
      const duration = perspMatch[2]
      const info1 = perspMatch[4]
      const info2 = nextPersp?.[3]
      if (nextPersp && edgesStr !== undefined && model !== undefined && duration !== undefined && info1 !== undefined && info2 !== undefined) {
        const card: CardItem = {
          type: 'perspective',
          id: entry.id,
          time,
          model,
          duration,
          lowerEdge: perspMatch[3] === '_',
          leftEdge: edgesStr.includes('/'),
          upperEdge: edgesStr.includes('_'),
          rightEdge: edgesStr.includes('\\'),
          info1,
          info2,
          rawText: entry.text + '\n' + nextPerspectiveEntry.text,
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
      const header = mapHeaderMatch[1]
      if (!header) break
      const cols = header.trim().split(/\s+/)
      const rows: Array<{ rowNum: number; cells: string[] }> = []
      const rawLines = [entry.text]
      let rIdx = index + 1

      while (rIdx < entries.length) {
        const rowEntry = entries[rIdx]
        if (!rowEntry) break
        const rMsg = extractLogMessage(rowEntry.text).message
        const rowMatch = /^\s*(\d{1,2})\s+(([A-Za-z0-9_=+-]{2}\s*)+)$/.exec(rMsg)
        const rowNumText = rowMatch?.[1]
        const cellsText = rowMatch?.[2]
        if (rowMatch && rowNumText !== undefined && cellsText !== undefined) {
          const rowNum = parseInt(rowNumText, 10)
          const cells = cellsText.trim().split(/\s+/)
          rows.push({ rowNum, cells })
          rawLines.push(rowEntry.text)
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
      const header = costHeaderMatch[1]
      if (!header) break
      const cols = header.trim().split(/\s+/)
      const rows: Array<{ rowNum: number; values: string[] }> = []
      const rawLines = [entry.text]
      let rIdx = index + 1

      while (rIdx < entries.length) {
        const rowEntry = entries[rIdx]
        if (!rowEntry) break
        const rMsg = extractLogMessage(rowEntry.text).message
        const fields = rMsg.trim().split(/[ \t]+/).filter(Boolean)
        const rowToken = fields[0] ?? ''
        const values = fields.slice(1)
        if (isAsciiDigits(rowToken, 1, 2) && values.length > 0 && values.every(isCostValue)) {
          const rowNum = Number(rowToken)
          rows.push({ rowNum, values })
          rawLines.push(rowEntry.text)
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
        const rowEntry = entries[rIdx]
        if (!rowEntry) break
        const rMsg = extractLogMessage(rowEntry.text).message.trim()
        if (/^(([A-Za-z0-9_=+-]{2}|\.\.)\s*){3,}$/.test(rMsg) && !/^\d+/.test(rMsg)) {
          rows.push(rMsg.split(/\s+/))
          rawLines.push(rowEntry.text)
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
          title: rows[0]?.includes('..') ? '局部海域扫描切片 (Local View)' : '大世界战略雷达扫描 (Radar Map)',
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
    const attrKey = attrMatch?.[1]
    const attrValue = attrMatch?.[2]
    if (attrMatch && attrKey !== undefined && attrValue !== undefined && !trimmedMsg.startsWith('http') && !trimmedMsg.startsWith('E:') && !trimmedMsg.startsWith('C:')) {
      const items = [{ key: attrKey.trim(), value: attrValue.trim() }]
      const rawLines = [entry.text]
      let rIdx = index + 1

      while (rIdx < entries.length) {
        const rowEntry = entries[rIdx]
        if (!rowEntry) break
        const rMsg = extractLogMessage(rowEntry.text).message.trim()
        const nextAttr = /^\s*([^:\n]{2,22}):\s*(.+)$/.exec(rMsg)
        const nextKey = nextAttr?.[1]
        const nextValue = nextAttr?.[2]
        if (nextAttr && nextKey !== undefined && nextValue !== undefined && !rMsg.startsWith('http') && !rMsg.startsWith('E:') && !rMsg.startsWith('C:')) {
          items.push({ key: nextKey.trim(), value: nextValue.trim() })
          rawLines.push(rowEntry.text)
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
        const rawLine = lines[i]
        const l = rawLine?.trim() ?? ''
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
        const excName = excMatch?.[1] && excMatch[2] !== undefined ? `${excMatch[1]}: ${excMatch[2]}` : 'Python 异常堆栈'
      index++
      const card: CardItem = {
        type: 'traceback',
        id: entry.id,
        time,
        excName,
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
        const modelName = modelMatch?.[1]
        if (modelName) {
          model = modelName
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

  const firstEntry = entries[0]
  if (!firstEntry) return []
  const dropped = lastEntries.findIndex(entry => entry.id === firstEntry.id)
  const overlap = lastEntries.length - dropped
  if (dropped >= 0 && entries.length >= overlap) {
    let matched = 0
    while (matched < overlap) {
      const entry = entries[matched]
      const cached = lastEntries[dropped + matched]
      if (!entry || !cached || (entry !== cached && (entry.id !== cached.id || entry.text !== cached.text || entry.level !== cached.level))) break
      matched++
    }
    if (matched === overlap) {
      if (dropped === 0 && entries.length === overlap) return lastCards

      // 末尾四张重新解析，允许追加条目补全横幅、海图和属性块。
      const tailIndex = lastRanges.length - 4
      const reuseIndex = lastRanges.findIndex(range => range.start >= dropped)
      if (reuseIndex >= 0 && reuseIndex < tailIndex) {
        const reuseRange = lastRanges[reuseIndex]
        const tailRange = lastRanges[tailIndex]
        if (reuseRange && tailRange) {
          const headEnd = reuseRange.start - dropped
          const head = aggregateSlice(entries, 0, headEnd)
          // 裁剪若切开多行卡片，重新解析的首张卡片可能跨过旧边界。
          if ((head.ranges.at(-1)?.end ?? 0) === headEnd) {
            const tail = aggregateSlice(entries, tailRange.start - dropped)
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
  }

  const full = aggregateSlice(entries)
  lastCards = full.cards
  lastRanges = full.ranges
  lastEntries = entries
  return lastCards
}

/** 聚合结果的数据类型，供消费方与测试复用。 */
export type {
  CardItem,
  CardRange,
}
