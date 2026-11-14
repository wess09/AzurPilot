/**
 * @fileoverview 日志正文词法 token 渲染与 LRU 缓存。
 * 从 LogCardView.tsx 原 58-186 行提取，纯搬迁未改动。
 */

import {
  Fragment,
  type ReactNode,
} from 'react'

// 提取日志消息正文（剥离 LEVEL HH:MM:SS.mmm │ 前缀）。
function extractLogMessage(raw: string): { level: string; time: string; message: string } {
  const match = /^([A-Z]{4,8})\s+(?:(\d{4}-\d{2}-\d{2})\s+)?(\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)\s*│\s*([\s\S]*)$/.exec(raw)
  if (match) {
    return { level: match[1] ?? 'INFO', time: match[3] ?? '', message: match[4] ?? raw }
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

export {
  TOKEN_REGEX,
  extractLogMessage,
  getCachedTokens,
  setCachedTokens,
  renderSearchHighlights,
}
