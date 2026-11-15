/**
 * @fileoverview Python Traceback 解析、栈帧视图与错误上下文卡片。
 * 从 LogCardView.tsx 原 1275-1613 行提取，纯搬迁未改动。
 */

import {
  memo,
  useMemo,
  useState,
} from 'react'
import {
  AlertCircle,
  Terminal,
} from 'lucide-react'
import type { CardItem } from './aggregate'
import { CopyButton } from './shared'

interface StackCodeLine {
  /** 源码行号。 */
  lineNum: number
  /** 是否为抛错的帧行，渲染时高亮。 */
  isFault: boolean
  /** 清理分隔符后的源码文本。 */
  code: string
}

interface StackLocalVar {
  /** 变量名。 */
  name: string
  /** 变量值文本。 */
  value: string
}

interface ParsedStackFrame {
  /** 原始文件路径。 */
  file: string
  /** 仅文件名部分，用于展示。 */
  fileName: string
  /** 出错行号。 */
  line: number
  /** 函数名。 */
  func: string
  /** 该帧上下文的源码行。 */
  codeLines: StackCodeLine[]
  /** 该帧的局部变量表。 */
  locals: StackLocalVar[]
}

interface ParsedTraceback {
  /** 从顶到底的调用栈帧。 */
  frames: ParsedStackFrame[]
  /** 异常摘要行（最后的 `XxxError: ...`）。 */
  excLine: string
  /** 原始 Traceback 文本，供复制与兜底展示。 */
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
    if (rawLine === undefined) continue
    const stripped = rawLine.replace(/^[│\s]+|[│\s]+$/g, '').trim()

    // 检查最后的异常类型与说明：ScriptEnd: ... 或 FooError: ...。
    const excMatch = rawLine.match(/^([a-zA-Z0-9_.]*(?:Error|Exception|Exit|Interrupt|ScriptEnd))(?::\s*(.*))?$/)
    if (excMatch?.[1] && !rawLine.includes('Traceback') && !rawLine.includes('File ')) {
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
      const frameFile = frameMatch[1]
      const frameLine = frameMatch[2]
      if (frameFile === undefined || frameLine === undefined) continue
      const fullPath = frameFile.trim()
      const fileName = fullPath.split(/[\\\/]/).pop() || fullPath
      currentFrame = {
        file: fullPath,
        fileName,
        line: parseInt(frameLine, 10),
        func: (frameMatch[3] ?? '<module>').trim(),
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
      const localName = localMatch?.[1]
      const localValue = localMatch?.[2]
      if (localMatch && localName && localName !== 'locals' && localValue !== undefined) {
        currentLocals.push({ name: localName, value: localValue.replace(/\s*│$/, '').trim() })
      }
      continue
    }

    // 匹配 Rich 代码行（含行号、故障标记 ❱/▶/> 与代码）。
    const richCodeMatch = rawLine.match(/[│]?\s*(❱|▶|>)?\s*(\d+)\s*│\s*(.*?)\s*[│]?$/)
    const codeLineNum = richCodeMatch?.[2]
    const codeText = richCodeMatch?.[3]
    if (richCodeMatch && codeLineNum !== undefined && codeText !== undefined) {
      const isFault = Boolean(richCodeMatch[1])
      const lineNum = parseInt(codeLineNum, 10)
      const code = codeText.replace(/[│\s]+$/, '')
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
const ErrorContextCard = memo(
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
const TracebackCard = memo(
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

/** 堆栈解析结果的数据类型，供渲染层与测试复用。 */
export type {
  StackCodeLine,
  StackLocalVar,
  ParsedStackFrame,
  ParsedTraceback,
}

export {
  normalizeCodeLines,
  parseTraceback,
  TracebackViewer,
  ErrorContextCard,
  TracebackCard,
}
