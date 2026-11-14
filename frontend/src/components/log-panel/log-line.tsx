/**
 * @fileoverview 单行日志渲染：分割线/等级行/居中标题/原文行的判定与展示。
 * 从 LogPanel.tsx 原 115-187 行提取，纯搬迁未改动。
 */

import { memo } from 'react'
import type { LogEntry } from '../../api/types'
import { CENTER_TITLE_RE, LOG_LINE_RE, PURE_RULE_RE, RULE_RE } from './buffer'
import { renderTokens } from '../LogCardView'

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
  const title = ruleMatch?.[1]?.trim()
  if (ruleMatch && title) {
    const char = trimmed.includes('═') ? '═' : '─'
    const ruleTitle = ruleMatch?.[1]?.trim()
    return ruleTitle ? (
      <div className={`log-rule ${char === '═' ? 'rule-double' : 'rule-single'}${freshClass}`} data-line-id={entry.id}>
        <span className="rule-bar" />
        <span className="rule-title">{renderTokens(ruleTitle, search)}</span>
        <span className="rule-bar" />
      </div>
    ) : null
  }

  const logMatch = LOG_LINE_RE.exec(rawText)
  if (logMatch) {
    const levelStr = logMatch[1]
    const dateStr = logMatch[2]
    const timeStr = logMatch[3]
    const messageStr = logMatch[4]
    if (levelStr === undefined || timeStr === undefined || messageStr === undefined) return null
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
  const centerTitle = centerMatch?.[1]?.trim()
  const shouldCenter = Boolean(
    isSingleLine && trimmed && (
      isCenter ||
      centerTitle
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
