/**
 * @fileoverview 流式日志纯数据域：行格式正则、微批缓冲、跟随步长、行高布局与安全截断合并。
 * 从 LogPanel.tsx 原 25-112 行提取，纯搬迁未改动。
 */

import type { LogEntry } from '../../api/types'

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
/** 微批提交间隔：连续推送时每 50ms 最多提交一次日志列表，给滚动和拖拽留出渲染时间。 */
export const LOG_RENDER_INTERVAL_MS = 50
/** 行数超过该阈值才启用虚拟滚动，短日志直接整段渲染。 */
export const VIRTUAL_LINE_THRESHOLD = 120
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
    const entry = entries[index]
    const height = entry ? measured.get(entry.id) ?? estimate : estimate
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
    if (recent.every((entry, index) => {
      const previousEntry = recent[index - 1]
      return entry.id > (previousEntry ? previousEntry.id : lastId)
    })) {
    if (!recent.length) return retained
    return retained.slice(Math.max(0, retained.length + recent.length - LOG_ENTRY_LIMIT)).concat(recent)
  }
  const entries = new Map<number, LogEntry>()
  if (!reset) for (const entry of previous.slice(-LOG_ENTRY_LIMIT)) entries.set(entry.id, entry)
  for (const entry of recent) entries.set(entry.id, entry)
  return [...entries.values()].sort((a, b) => a.id - b.id).slice(-LOG_ENTRY_LIMIT)
}
