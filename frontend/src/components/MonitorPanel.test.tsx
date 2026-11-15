/** @fileoverview MonitorPanel 最近日志的解析回归：帧归并、分割线降噪与标准行拆分。 */

import { describe, expect, it } from 'vitest'
import { compactLine, mergeLines, RECENT_LOG_LINES } from './MonitorPanel'
import type { LogEntry } from '../api/types'

const line = (id: number, text: string, level = 'INFO'): LogEntry => ({id, level, text})

describe('MonitorPanel 截图视图的最近日志', () => {
  it('连续帧归并保留时间且大批日志缓存有界', () => {
    let pending = mergeLines([], [line(0, 'WARNING  2026-09-13 23:24:47.008 │ 开始')], true)
    expect(mergeLines([], pending, true)[0]?.time).toBe('2026-09-13 23:24:47.008')
    for (let id = 1; id <= 1000; id++) pending = mergeLines(pending, [line(id, `步骤 ${id}`)], false)
    expect(pending.map(item => item.id)).toEqual([998, 999, 1000])
    expect(mergeLines(pending, [line(1, '重置')], true).map(item => item.text)).toEqual(['重置'])
  })
  it('丢弃没有信息量的纯分割线', () => {
    expect(compactLine(line(1, '═'.repeat(60)))).toBeNull()
    expect(compactLine(line(2, '─'.repeat(40)))).toBeNull()
    expect(compactLine(line(3, '   '))).toBeNull()
  })

  it('带标题的分割线只保留标题', () => {
    const compact = compactLine(line(1, `${'═'.repeat(20)} COMMISSION ${'═'.repeat(20)}`))
    expect(compact).toMatchObject({level: 'info', time: '', text: 'COMMISSION'})
  })

  it('标准日志行拆出级别、时间与正文', () => {
    const compact = compactLine(line(1, 'WARNING  2026-09-13 23:24:47.008 │ <<< HR3 >>>', 'WARNING'))
    expect(compact).toMatchObject({level: 'warning', time: '2026-09-13 23:24:47.008', text: '<<< HR3 >>>'})
  })

  it('多行 Traceback 折成一行且不丢内容', () => {
    const compact = compactLine(line(1, 'Traceback (most recent call last):\n  File "a.py", line 1\nValueError: x', 'ERROR'))
    expect(compact?.text).toBe('Traceback (most recent call last):   File "a.py", line 1 ValueError: x')
    expect(compact?.level).toBe('error')
  })

  it('合并增量并只保留最后几条', () => {
    const merged = mergeLines([], Array.from({length: 5}, (_, index) => line(index + 1, `step ${index + 1}`)), false)
    expect(merged).toHaveLength(RECENT_LOG_LINES)
    expect(merged.map(item => item.id)).toEqual([3, 4, 5])
  })

  it('只保留可展示的行，分割线不占用名额', () => {
    const merged = mergeLines([], [line(1, '═'.repeat(40)), line(2, 'start'), line(3, 'end')], false)
    expect(merged.map(item => item.text)).toEqual(['start', 'end'])
  })

  it('游标重置时丢弃旧内容', () => {
    const previous = mergeLines([], [line(1, 'old'), line(2, 'older')], false)
    expect(mergeLines(previous, [line(1, 'fresh')], true).map(item => item.text)).toEqual(['fresh'])
  })
})
