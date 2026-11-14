/**
 * 从 LogPanel.tsx 原 190-219 行提取，纯搬迁未改动。
 * 日志过滤偏好：等级档位、过滤判定与 localStorage 持久化读取。
 */

import type { LogEntry } from '../../api/types'

export const LOG_LEVELS = ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

export function filterLogEntries(entries: LogEntry[], floor: number, level: string, search: string) {
  if ((entries[0]?.id ?? Infinity) > floor && level === 'ALL' && !search) return entries
  return entries.filter(entry =>
    entry.id > floor &&
    (level === 'ALL' || entry.level === level) &&
    (!search || entry.text.toLowerCase().includes(search))
  )
}

export function loadLogLevel(instance: string): string {
  try {
    const saved = localStorage.getItem(`azurpilot.log.level.${instance}`)
    if (saved && LOG_LEVELS.includes(saved)) return saved
  } catch { /* 存储不可用时使用默认等级。 */ }
  return 'ALL'
}

/** 日志排序：默认正序（旧→新），与自动滚到底的行为配套。 */
export function loadLogDescending(instance: string): boolean {
  try { return localStorage.getItem(`azurpilot.log.order.${instance}`) === 'desc' } catch { return false }
}

export function loadLogViewMode(): 'cards' | 'classic' {
  try {
    const saved = localStorage.getItem('azurpilot.log.viewMode')
    if (saved === 'cards' || saved === 'classic') return saved
  } catch { /* 存储不可用时默认卡片视图 */ }
  return 'cards'
}
