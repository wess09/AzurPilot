/**
 * @fileoverview 支持数学公式与代码高亮的 Markdown 渲染组件。
 */

import { useMemo, type MouseEvent } from 'react'
import { Marked, type Token } from 'marked'
import katex from 'katex'
import hljs from 'highlight.js'
import DOMPurify, { type Config } from 'dompurify'
import 'katex/dist/katex.min.css'
import 'highlight.js/styles/atom-one-dark.css'

interface MarkdownViewProps {
  content: string
  className?: string
}

// 独立的 marked 实例：数学公式等扩展只注册到这份解析器，不波及全局默认实例。
const markedInstance = new Marked({
  gfm: true,
  breaks: true,
})

// 注册数学公式扩展（支持 $$ 块级与 $ 行内）
markedInstance.use({
  extensions: [
    {
      name: 'mathBlock',
      level: 'block',
      start(src: string) {
        return src.indexOf('$$')
      },
      tokenizer(src: string) {
        const match = /^\$\$([\s\S]+?)\$\$/.exec(src)
        if (match) {
          return {
            type: 'mathBlock',
            raw: match[0],
            text: match[1].trim(),
          }
        }
        return undefined
      },
      renderer(token: { text?: string } & Token) {
        const formula = token.text || ''
        try {
          const rendered = katex.renderToString(formula, {
            displayMode: true,
            throwOnError: false,
          })
          return `<div class="md-math-block">${rendered}</div>`
        } catch {
          return `<pre class="md-math-fallback">${formula}</pre>`
        }
      },
    },
    {
      name: 'mathInline',
      level: 'inline',
      start(src: string) {
        return src.indexOf('$')
      },
      tokenizer(src: string) {
        const match = /^(?<!\\|\$)\$(?!\s)([^$\n]+?)(?<!\s)\$(?!\$)/.exec(src)
        if (match) {
          return {
            type: 'mathInline',
            raw: match[0],
            text: match[1].trim(),
          }
        }
        return undefined
      },
      renderer(token: { text?: string } & Token) {
        const formula = token.text || ''
        try {
          const rendered = katex.renderToString(formula, {
            displayMode: false,
            throwOnError: false,
          })
          return `<span class="md-math-inline">${rendered}</span>`
        } catch {
          return `<code class="md-math-fallback">${formula}</code>`
        }
      },
    },
  ],
})

// 自定义渲染器：支持代码块语法高亮、GitHub 风格提示块 (> [!NOTE] 等) 以及安全外链
markedInstance.use({
  renderer: {
    code({ text, lang }: { text: string; lang?: string }) {
      const language = (lang || '').trim().toLowerCase()
      let highlighted = ''
      if (language && hljs.getLanguage(language)) {
        try {
          highlighted = hljs.highlight(text, { language, ignoreIllegals: true }).value
        } catch {
          highlighted = hljs.highlightAuto(text).value
        }
      } else {
        try {
          highlighted = hljs.highlightAuto(text).value
        } catch {
          highlighted = text
        }
      }

      const langLabel = language || 'code'
      return `<div class="md-code-wrap"><div class="md-code-header"><span class="md-code-lang">${langLabel}</span><button type="button" class="md-code-copy" data-code="${encodeURIComponent(text)}">复制</button></div><pre class="md-pre"><code class="hljs language-${language}">${highlighted}</code></pre></div>`
    },
    blockquote({ text }: { text: string }) {
      const alertMatch = text.match(/^\s*(?:<p>)?\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\](?:\s*<br\s*\/?>|\s*\n|\s+)?([\s\S]*)$/i)
      if (alertMatch) {
        const type = alertMatch[1].toUpperCase()
        const body = alertMatch[2].replace(/<\/p>\s*$/, '')
        const typeLabels: Record<string, string> = {
          NOTE: '说明',
          TIP: '提示',
          IMPORTANT: '重要',
          WARNING: '警告',
          CAUTION: '注意',
        }
        return `<div class="md-alert md-alert-${type.toLowerCase()}"><div class="md-alert-header"><span class="md-alert-badge">${typeLabels[type] || type}</span></div><div class="md-alert-body"><p>${body}</p></div></div>`
      }
      return `<blockquote>${text}</blockquote>`
    },
    link({ href, title, text }: { href: string; title?: string | null; text: string }) {
      const titleAttr = title ? ` title="${title}"` : ''
      return `<a href="${href}" target="_blank" rel="noopener noreferrer" class="md-link"${titleAttr}>${text}</a>`
    },
  },
})

// DOMPurify 配置：允许常见安全的富文本标签、代码块复制按钮、细节折叠、MathML 及 KaTeX 所需的类与属性
const DOMPURIFY_CONFIG: Config = {
  ADD_TAGS: [
    'details',
    'summary',
    'mark',
    'kbd',
    'font',
    'del',
    's',
    'u',
    'sub',
    'sup',
    'span',
    'div',
    'button',
    'pre',
    'code',
    'math',
    'semantics',
    'mrow',
    'mi',
    'mo',
    'mn',
    'annotation',
    'mfrac',
    'msup',
    'msub',
    'msubsup',
    'mtable',
    'mtr',
    'mtd',
    'svg',
    'path',
    'line',
  ],
  ADD_ATTR: [
    'target',
    'rel',
    'color',
    'open',
    'class',
    'aria-hidden',
    'role',
    'style',
    'viewBox',
    'xmlns',
    'd',
    'fill',
    'stroke',
    'data-code',
    'type',
  ],
}

const SSR_ALLOWED_TAGS = new Set([
  'a', 'abbr', 'b', 'blockquote', 'br', 'button', 'code', 'del', 'details', 'div', 'em',
  'font', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'i', 'img', 'input', 'kbd', 'li',
  'mark', 'ol', 'p', 'pre', 's', 'span', 'strong', 'sub', 'summary', 'sup', 'table',
  'tbody', 'td', 'tfoot', 'th', 'thead', 'tr', 'u', 'ul',
  'math', 'semantics', 'mrow', 'mi', 'mo', 'mn', 'annotation', 'mfrac', 'msup', 'msub',
  'msubsup', 'mtable', 'mtr', 'mtd', 'svg', 'path', 'line',
])

const SSR_ALLOWED_ATTRS = new Set([
  'alt', 'aria-hidden', 'checked', 'class', 'color', 'd', 'data-code', 'disabled',
  'encoding', 'fill', 'height', 'href', 'open', 'rel', 'role', 'src', 'stroke', 'style',
  'target', 'title', 'type', 'viewbox', 'width', 'xmlns',
])

const SSR_DROP_CONTENT_TAGS = new Set([
  'script', 'style', 'iframe', 'object', 'embed', 'template', 'noscript',
])

function htmlEscapeAttribute(value: string): string {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('"', '&quot;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
}

function safeHtmlUrl(value: string, attribute: string): boolean {
  let normalized = ''
  for (const char of value.trim()) {
    const code = char.charCodeAt(0)
    if (code > 0x20 && code !== 0x7f) normalized += char
  }
  const lower = normalized.toLowerCase()
  if (!lower) return true
  if (lower.startsWith('#') || lower.startsWith('/') || lower.startsWith('./') || lower.startsWith('../')) return true
  if (lower.startsWith('https:') || lower.startsWith('http:') || lower.startsWith('mailto:') || lower.startsWith('tel:')) return true
  return attribute === 'src' && lower.startsWith('data:image/')
}

function findHtmlTagEnd(html: string, start: number): number {
  let quote = ''
  for (let index = start + 1; index < html.length; index++) {
    const char = html[index]
    if (quote) {
      if (char === quote) quote = ''
      continue
    }
    if (char === '"' || char === "'") {
      quote = char
      continue
    }
    if (char === '>') return index
  }
  return -1
}

function sanitizeSsrTag(raw: string): {html: string; name: string; closing: boolean; dropContent: boolean} {
  let cursor = 1
  while (cursor < raw.length && raw[cursor] <= ' ') cursor++

  let closing = false
  if (raw[cursor] === '/') {
    closing = true
    cursor++
    while (cursor < raw.length && raw[cursor] <= ' ') cursor++
  }

  const nameStart = cursor
  while (cursor < raw.length) {
    const char = raw[cursor]
    const code = char.charCodeAt(0)
    const isName = (code >= 48 && code <= 57) || (code >= 65 && code <= 90)
      || (code >= 97 && code <= 122) || char === ':' || char === '-'
    if (!isName) break
    cursor++
  }
  const name = raw.slice(nameStart, cursor).toLowerCase()
  if (!name) return {html: '', name: '', closing, dropContent: false}

  const dropContent = SSR_DROP_CONTENT_TAGS.has(name)
  if (dropContent || !SSR_ALLOWED_TAGS.has(name)) {
    return {html: '', name, closing, dropContent}
  }
  if (closing) return {html: `</${name}>`, name, closing, dropContent: false}

  const attributes: string[] = []
  let selfClosing = false
  while (cursor < raw.length) {
    while (cursor < raw.length && raw[cursor] <= ' ') cursor++
    if (raw[cursor] === '>' || cursor >= raw.length) break
    if (raw[cursor] === '/') {
      selfClosing = true
      cursor++
      continue
    }

    const attrStart = cursor
    while (cursor < raw.length) {
      const char = raw[cursor]
      if (char <= ' ' || char === '=' || char === '>' || char === '/') break
      cursor++
    }
    const attrName = raw.slice(attrStart, cursor).toLowerCase()
    if (!attrName) {
      cursor++
      continue
    }

    while (cursor < raw.length && raw[cursor] <= ' ') cursor++
    let value: string | null = null
    if (raw[cursor] === '=') {
      cursor++
      while (cursor < raw.length && raw[cursor] <= ' ') cursor++
      const quote = raw[cursor] === '"' || raw[cursor] === "'" ? raw[cursor++] : ''
      const valueStart = cursor
      if (quote) {
        while (cursor < raw.length && raw[cursor] !== quote) cursor++
        value = raw.slice(valueStart, cursor)
        if (raw[cursor] === quote) cursor++
      } else {
        while (cursor < raw.length) {
          const char = raw[cursor]
          if (char <= ' ' || char === '>' || char === '/') break
          cursor++
        }
        value = raw.slice(valueStart, cursor)
      }
    }

    if (attrName.startsWith('on') || !SSR_ALLOWED_ATTRS.has(attrName)) continue
    if ((attrName === 'href' || attrName === 'src') && value !== null && !safeHtmlUrl(value, attrName)) continue
    attributes.push(value === null ? attrName : `${attrName}="${htmlEscapeAttribute(value)}"`)
  }

  const attrs = attributes.length ? ` ${attributes.join(' ')}` : ''
  return {html: `<${name}${attrs}${selfClosing ? ' /' : ''}>`, name, closing, dropContent: false}
}

function sanitizeSsrHtml(html: string): string {
  let output = ''
  let cursor = 0
  while (cursor < html.length) {
    const tagStart = html.indexOf('<', cursor)
    if (tagStart < 0) {
      output += html.slice(cursor)
      break
    }
    output += html.slice(cursor, tagStart)

    const tagEnd = findHtmlTagEnd(html, tagStart)
    if (tagEnd < 0) {
      output += '&lt;' + html.slice(tagStart + 1)
      break
    }

    const raw = html.slice(tagStart, tagEnd + 1)
    const tag = sanitizeSsrTag(raw)
    if (tag.dropContent && !tag.closing) {
      const closePrefix = `</${tag.name}`
      const lower = html.toLowerCase()
      const closeStart = lower.indexOf(closePrefix, tagEnd + 1)
      if (closeStart < 0) {
        cursor = html.length
        break
      }
      const closeEnd = findHtmlTagEnd(html, closeStart)
      cursor = closeEnd < 0 ? html.length : closeEnd + 1
      continue
    }

    output += tag.html
    cursor = tagEnd + 1
  }
  return output
}

function sanitizeHtml(html: string): string {
  if (typeof window !== 'undefined' && typeof DOMPurify.sanitize === 'function') {
    return DOMPurify.sanitize(html, DOMPURIFY_CONFIG)
  }
  // React SSR / Vitest 的 Node 环境没有浏览器 DOM。这里使用线性 tokenizer 做白名单过滤，
  // 不使用正则「删除危险片段」，因此不会出现多次替换绕过或 ReDoS。
  return sanitizeSsrHtml(html)
}

/**
 * 专为公告等富文本内容设计的高性能 Markdown / 语法高亮 / LaTeX 公式 / 安全 HTML 渲染器。
 * 底层基于 Marked + Highlight.js + KaTeX + DOMPurify，全面支持 CommonMark、GFM、代码语法高亮与数学公式。
 */
export function MarkdownView({ content, className = '' }: MarkdownViewProps) {
  const html = useMemo(() => {
    if (!content) return ''
    try {
      const parsed = markedInstance.parse(content) as string
      return sanitizeHtml(parsed)
    } catch {
      return sanitizeHtml(content)
    }
  }, [content])

  // 正文是整块注入的 innerHTML，里面的复制按钮接不到 React 事件：在容器上做一次事件委托。
  const handleContainerClick = (e: MouseEvent<HTMLDivElement>) => {
    const target = (e.target as HTMLElement).closest('.md-code-copy') as HTMLElement | null
    if (target) {
      const encoded = target.getAttribute('data-code')
      if (encoded) {
        const code = decodeURIComponent(encoded)
        if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
          void navigator.clipboard.writeText(code)
        }
        const originalText = target.innerText
        target.innerText = '已复制!'
        target.classList.add('copied')
        setTimeout(() => {
          target.innerText = originalText
          target.classList.remove('copied')
        }, 2000)
      }
    }
  }

  if (!html) return null

  return (
    <div
      className={`markdown-view ${className}`.trim()}
      onClick={handleContainerClick}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
