/**
 * @fileoverview LogPanel 的解析、渲染与缓冲回归：超大日志截断、分割线与居中标题识别、流式微批队列与行高布局。
 */

import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import {
  LogLine,
  LOG_LINE_RE,
  RULE_RE,
  PURE_RULE_RE,
  CENTER_TITLE_RE,
  LOG_ENTRY_LIMIT,
  LINE_HEIGHT_ESTIMATE,
  buildLineLayout,
  mergeLogEntries,
  queueLogEvent,
  type LogBufferState,
} from './LogPanel'

describe('LogPanel 日志解析与渲染', () => {
  it('超大历史日志在进入 React state 前截断到客户端上限', () => {
    const entries = Array.from({length: 42_000}, (_, index) => ({
      id: index + 1,
      level: 'INFO',
      text: `INFO 2026-09-22 00:00:00 │ 日志 ${index + 1}`,
    }))

    const retained = mergeLogEntries([], entries, true)
    expect(retained).toHaveLength(LOG_ENTRY_LIMIT)
    expect(retained[0].id).toBe(42_000 - LOG_ENTRY_LIMIT + 1)
    expect(retained.at(-1)?.id).toBe(42_000)
  })

  it('增量合并去重、排序且始终保持渲染上限', () => {
    const previous = Array.from({length: LOG_ENTRY_LIMIT}, (_, index) => ({
      id: index + 1, level: 'INFO', text: `旧日志 ${index + 1}`,
    }))
    const incoming = [
      {id: LOG_ENTRY_LIMIT, level: 'WARNING', text: '重复条目以新值为准'},
      {id: LOG_ENTRY_LIMIT + 2, level: 'INFO', text: '后到但编号更大'},
      {id: LOG_ENTRY_LIMIT + 1, level: 'INFO', text: '新日志'},
    ]

    const retained = mergeLogEntries(previous, incoming)
    expect(retained).toHaveLength(LOG_ENTRY_LIMIT)
    expect(retained[0].id).toBe(3)
    expect(retained.at(-1)?.id).toBe(LOG_ENTRY_LIMIT + 2)
    expect(retained.find(entry => entry.id === LOG_ENTRY_LIMIT)?.level).toBe('WARNING')
  })

  it('正确识别 level=0 居中标题与纯双分割线', () => {
    const doubleRule = '═'.repeat(60)
    expect(PURE_RULE_RE.test(doubleRule)).toBe(true)

    const centerTitleText = ' '.repeat(20) + 'COMMISSION' + ' '.repeat(20)
    expect(CENTER_TITLE_RE.test(centerTitleText)).toBe(true)

    const htmlCenter = renderToStaticMarkup(
      <LogLine entry={{ id: 2, level: 'INFO', text: centerTitleText }} search="" />
    )
    expect(htmlCenter).toContain('log-center-title')
    expect(htmlCenter).toContain('center-title-text')
    expect(htmlCenter).toContain('COMMISSION')
    expect(htmlCenter).not.toContain('rule-bar')
  })

  it('在空格被剥离时，仍可通过夹心上下文将 level=0 标题居中', () => {
    // 假设极端情况下前后端空格丢失，只有 `COMMISSION` 一个词
    const htmlCenterByContext = renderToStaticMarkup(
      <LogLine entry={{ id: 2, level: 'INFO', text: 'COMMISSION' }} search="" isCenter={true} />
    )
    expect(htmlCenterByContext).toContain('log-center-title')
    expect(htmlCenterByContext).toContain('center-title-text')
    expect(htmlCenterByContext).toContain('COMMISSION')
  })

  it('level=1 与 level=2 带线标题正确渲染两端横线', () => {
    const level1Text = '═'.repeat(20) + ' COMMISSION ' + '═'.repeat(20)
    expect(RULE_RE.test(level1Text)).toBe(true)
    const htmlLevel1 = renderToStaticMarkup(
      <LogLine entry={{ id: 1, level: 'INFO', text: level1Text }} search="" />
    )
    expect(htmlLevel1).toContain('rule-double')
    expect(htmlLevel1).toContain('rule-title')
    expect(htmlLevel1).toContain('rule-bar')

    const level2Text = '─'.repeat(20) + ' SUB_STAGE ' + '─'.repeat(20)
    expect(RULE_RE.test(level2Text)).toBe(true)
    const htmlLevel2 = renderToStaticMarkup(
      <LogLine entry={{ id: 2, level: 'INFO', text: level2Text }} search="" />
    )
    expect(htmlLevel2).toContain('rule-single')
    expect(htmlLevel2).toContain('rule-title')
    expect(htmlLevel2).toContain('rule-bar')
  })

  it('标准日志行正确渲染级别、时间戳和分隔符', () => {
    const line = 'INFO     2026-09-13 23:24:47.008 │ <<< HR3 >>>'
    expect(LOG_LINE_RE.test(line)).toBe(true)
    const html = renderToStaticMarkup(
      <LogLine entry={{ id: 3, level: 'INFO', text: line }} search="" />
    )
    expect(html).toContain('lvl-info')
    expect(html).toContain('2026-09-13 23:24:47.008')
    expect(html).toContain('log-divider')
    expect(html).toContain('hl-title')
  })

  it('中文方括号标签与英文标签同样按属性着色', () => {
    const line = 'INFO     2026-09-13 23:24:47.008 │ [配置] 已保存 ./config\ap.json'
    const html = renderToStaticMarkup(
      <LogLine entry={{ id: 4, level: 'INFO', text: line }} search="" />
    )
    expect(html).toContain('hl-attr')
    expect(html).toContain('hl-path')
  })

  it('普通代码缩进或 Traceback 不会误判为居中标题', () => {
    const indentedCode = '    def some_function():'
    expect(CENTER_TITLE_RE.test(indentedCode)).toBe(false)
    const html = renderToStaticMarkup(
      <LogLine entry={{ id: 4, level: 'INFO', text: indentedCode }} search="" />
    )
    expect(html).not.toContain('log-center-title')
    expect(html).toContain('log-raw')
  })

  it('居中标题支持搜索高亮', () => {
    const centerTitleText = ' '.repeat(20) + 'START_TASK' + ' '.repeat(20)
    const html = renderToStaticMarkup(
      <LogLine entry={{ id: 5, level: 'INFO', text: centerTitleText }} search="start" />
    )
    expect(html).toContain('log-center-title')
    expect(html).toContain('log-search-match')
    expect(html).toContain('START')
  })

  describe('流式日志微批处理缓冲队列 (queueLogEvent)', () => {
    it('短时间多批次事件连续累加且更新最新 cursor', () => {
      const buffer: LogBufferState = { entries: [], reset: false, cursor: null }
      queueLogEvent(buffer, {
        entries: [{ id: 1, level: 'INFO', text: '行 1' }],
        cursor: 10,
      })
      queueLogEvent(buffer, {
        entries: [
          { id: 2, level: 'INFO', text: '行 2' },
          { id: 3, level: 'INFO', text: '行 3' },
        ],
        cursor: 12,
      })

      expect(buffer.entries).toHaveLength(3)
      expect(buffer.entries.map(e => e.id)).toEqual([1, 2, 3])
      expect(buffer.reset).toBe(false)
      expect(buffer.cursor).toBe(12)
    })

    it('收到 reset=true 时清空此前缓冲日志并标记 reset，后续同批追加', () => {
      const buffer: LogBufferState = {
        entries: [
          { id: 1, level: 'INFO', text: '将被丢弃的旧缓冲' },
          { id: 2, level: 'INFO', text: '将被丢弃的旧缓冲' },
        ],
        reset: false,
        cursor: 5,
      }

      queueLogEvent(buffer, {
        entries: [{ id: 10, level: 'INFO', text: '重置后的第一条' }],
        reset: true,
        cursor: 20,
      })
      expect(buffer.reset).toBe(true)
      expect(buffer.entries).toHaveLength(1)
      expect(buffer.entries[0].id).toBe(10)
      expect(buffer.cursor).toBe(20)

      // 同一动画帧内后续到达的事件继续追加
      queueLogEvent(buffer, {
        entries: [{ id: 11, level: 'INFO', text: '紧随重置后的第二条' }],
        reset: false,
        cursor: 21,
      })
      expect(buffer.reset).toBe(true)
      expect(buffer.entries).toHaveLength(2)
      expect(buffer.entries.map(e => e.id)).toEqual([10, 11])
      expect(buffer.cursor).toBe(21)
    })

    it('渲染暂停时限制待提交日志数量', () => {
      const buffer: LogBufferState = {entries: [], reset: false, cursor: null}
      const entries = Array.from({length: LOG_ENTRY_LIMIT + 5}, (_, index) => ({
        id: index + 1, level: 'INFO', text: `日志 ${index + 1}`,
      }))
      queueLogEvent(buffer, {entries, reset: true, cursor: entries.length})
      queueLogEvent(buffer, {
        entries: [{id: entries.length + 1, level: 'INFO', text: '最新日志'}],
        cursor: entries.length + 1,
      })
      expect(buffer.entries).toHaveLength(LOG_ENTRY_LIMIT)
      expect(buffer.entries[0].id).toBe(7)
      expect(buffer.entries.at(-1)?.id).toBe(entries.length + 1)
    })
  })

  it('行高布局用实测均高占位未渲染行，偏移逐行累加', () => {
    const entries = [
      {id: 1, level: 'INFO', text: '第一行'},
      {id: 2, level: 'INFO', text: '第二行'},
      {id: 3, level: 'INFO', text: '第三行'},
    ]
    const measured = new Map([[1, 40], [2, 60]])

    const layout = buildLineLayout(entries, measured, LINE_HEIGHT_ESTIMATE)

    expect(layout.heights).toEqual([40, 60, 50])
    expect(layout.offsets).toEqual([0, 40, 100])
    expect(layout.total).toBe(150)
  })

  it('一条都没实测时用固定估值占位', () => {
    const entries = [{id: 1, level: 'INFO', text: '唯一行'}]

    const layout = buildLineLayout(entries, new Map(), LINE_HEIGHT_ESTIMATE)

    expect(layout.heights).toEqual([LINE_HEIGHT_ESTIMATE])
    expect(layout.total).toBe(LINE_HEIGHT_ESTIMATE)
  })
})
