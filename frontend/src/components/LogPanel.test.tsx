import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { LogLine, LOG_LINE_RE, RULE_RE, PURE_RULE_RE, CENTER_TITLE_RE, mergeLogEntries } from './LogPanel'

describe('LogPanel 日志解析与渲染', () => {
  it('正确识别 level=0 居中标题与纯双分割线', () => {
    const doubleRule = '═'.repeat(60)
    expect(PURE_RULE_RE.test(doubleRule)).toBe(true)

    const centerTitleText = ' '.repeat(20) + 'COMMISSION' + ' '.repeat(20)
    expect(CENTER_TITLE_RE.test(centerTitleText)).toBe(true)

    // 单行居中渲染
    const htmlCenter = renderToStaticMarkup(
      <LogLine entry={{ id: 2, level: 'INFO', text: centerTitleText }} search="" />
    )
    expect(htmlCenter).toContain('log-center-title')
    expect(htmlCenter).toContain('center-title-text')
    expect(htmlCenter).toContain('COMMISSION')
    expect(htmlCenter).not.toContain('rule-bar')
  })

  it('在空格被剥离时，仍可通过夹心上下文将 level=0 标题居中', () => {
    // 假设极端情况下前后端空格丢失，只有 "COMMISSION"
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

  it('按 id 合并增量日志并在重置时整体替换', () => {
    const first = mergeLogEntries([], [{id: 1, level: 'INFO', text: 'a'}, {id: 2, level: 'INFO', text: 'b'}])
    const merged = mergeLogEntries(first, [{id: 2, level: 'INFO', text: 'b2'}, {id: 3, level: 'INFO', text: 'c'}])
    expect(merged.map(entry => [entry.id, entry.text])).toEqual([[1, 'a'], [2, 'b2'], [3, 'c']])
    expect(mergeLogEntries(merged, [{id: 9, level: 'ERROR', text: 'x'}], true)).toEqual([{id: 9, level: 'ERROR', text: 'x'}])
  })
})
