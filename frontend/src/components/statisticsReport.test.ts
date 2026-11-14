/** @fileoverview 统计报表紧凑点位的还原回归：时间文本还原与列式共用时间轴。 */

import {describe, expect, it} from 'vitest'
import {normalizeReport} from './statisticsData'

describe('统计报表的紧凑点位还原', () => {
  it('微秒整数还原成与原格式逐字一致的时间文本', () => {
    const report = {
      instance: 'ap', category: 'resources', month: '', metrics: [], tables: [], notes: [],
      series: [{key: 'oil', label: '石油', points: [
        {t: 1790951559404030, v: 1, s: 'ocr'},
        {t: 1790951559000000, v: 2},
        {t: 1767225600000001, v: 3},
      ]}],
    }
    const points = normalizeReport(report).series[0]?.points ?? []

    expect(points.map(point => point.time)).toEqual([
      '2026-10-02 14:32:39.404030',
      '2026-10-02 14:32:39',
      '2026-01-01 00:00:00.000001',
    ])
    expect(points.map(point => point.value)).toEqual([1, 2, 3])
    expect(points.map(point => point.source)).toEqual(['ocr', '', ''])
  })
  it('列式下发时按共用时间轴还原点位', () => {
    const report = {
      instance: 'ap', category: 'resources', month: '', metrics: [], tables: [], notes: [],
      axis: [1790951559404030, 1790951559000000, 1767225600000001],
      series: [
        {key: 'oil', label: '石油', values: [1, 2, 3]},
        {key: 'gem', label: '宝石', values: [4, 5, 6], sources: ['ocr', '', '']},
      ],
    }
    const series = normalizeReport(report).series

    expect(series[0]?.points.map(point => point.time)).toEqual([
      '2026-10-02 14:32:39.404030', '2026-10-02 14:32:39', '2026-01-01 00:00:00.000001',
    ])
    expect(series[0]?.points.map(point => point.value)).toEqual([1, 2, 3])
    expect(series[1]?.points.map(point => point.source)).toEqual(['ocr', '', ''])
  })
})
