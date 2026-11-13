/**
 * @fileoverview 统计数据管道的回归测试：线上格式折算、时间聚合、多源合并与涨跌分段。
 */

import { describe, expect, it } from 'vitest'
import {aggregatePoints, isActionPointSeries, mergeMultiSeriesRows, normalizeReport, riseFallDeltas, riseFallSegments} from './statisticsData'

describe('仓库趋势传输', () => {
  it('逐点和共用时间轴都保留物品模板图标与真实数量', () => {
    const base = {instance: 'test', category: 'storage', month: '2026-10', metrics: [], tables: [], notes: []}
    const icon = 'storage:storage_items/CognitiveChipsII'
    for (const wire of [
      {...base, series: [{key: 'chips', label: '心智单元II', icon, points: [{t: 1790985600000000, v: 1204, s: '仓库统计'}]}]},
      {...base, axis: [1790985600000000], series: [{key: 'chips', label: '心智单元II', icon, values: [1204], sources: ['仓库统计']}]},
    ]) {
      expect(normalizeReport(wire).series[0]).toEqual({key: 'chips', label: '心智单元II', icon,
        points: [{time: '2026-10-03 00:00:00', value: 1204, source: '仓库统计'}]})
    }
  })
})

describe('统计时间聚合', () => {
  it('K 线保留开高低收以及零值，不用平均值代替收盘', () => {
    const points = [10, 30, 0, 20].map((value, index) => ({time: `2026-09-13 10:0${index}:00`, value}))
    expect(aggregatePoints(points, 60)).toEqual([{time: '2026-09-13 10:00:00', open: 10, close: 20, low: 0, high: 30}])
  })
  it('日聚合按本地自然日分桶，原始视图保留同一时刻的多次记录', () => {
    const points = [{time: '2026-09-13 23:59:00', value: 1}, {time: '2026-09-14 00:01:00', value: 2}, {time: '2026-09-14 00:01:00', value: 3}]
    expect(aggregatePoints(points, 1440)).toHaveLength(2)
    expect(aggregatePoints(points, 0)).toHaveLength(3)
  })
})

describe('多数据源行合并', () => {
  it('按时间戳将多个数据源对齐合并并降序排列', () => {
    const seriesList = [
      {key: 'oil', label: '石油', points: [{time: '2026-09-20 12:00:00', value: 1000, source: '出击'}, {time: '2026-09-20 13:00:00', value: 900, source: '出击'}]},
      {key: 'coin', label: '物资', points: [{time: '2026-09-20 12:00:00', value: 50000, source: '出击'}, {time: '2026-09-20 14:00:00', value: 60000, source: '委托'}]},
      {key: 'cube', label: '魔方', points: [{time: '2026-09-20 13:00:00', value: 300, source: '出击'}]},
    ]
    const rows = mergeMultiSeriesRows(seriesList)
    expect(rows).toEqual([
      ['2026-09-20 14:00:00', '—', 60000, '—', '委托'],
      ['2026-09-20 13:00:00', 900, '—', 300, '出击'],
      ['2026-09-20 12:00:00', 1000, 50000, '—', '出击'],
    ])
  })

  it('支持时间范围过滤', () => {
    const seriesList = [
      {key: 'oil', label: '石油', points: [{time: '2026-09-20 10:00:00', value: 100}, {time: '2026-09-20 12:00:00', value: 200}]},
    ]
    const rows = mergeMultiSeriesRows(seriesList, '2026-09-20T11:00')
    expect(rows).toHaveLength(1)
    expect(rows[0][0]).toBe('2026-09-20 12:00:00')
  })
})

describe('riseFallDeltas', () => {
  it('首点记 0，其后按相邻两点做差', () => {
    expect(riseFallDeltas([10, 12, 9, 9, null, 15])).toEqual([0, 2, -3, 0, 0, 0])
  })
})

describe('riseFallSegments 与行动力识别', () => {
  it('按方向分段，涨与持平同组，段间用 "-" 断开', () => {
    const {rise, fall} = riseFallSegments([1, 2, 3, 4], [10, 12, 9, 9])
    expect(rise).toEqual([[1, 10], [2, 12], '-', [3, 9], [4, 9], '-'])
    expect(fall).toEqual([[2, 12], [3, 9], '-'])
  })

  it('行动力按固定键识别，标签可兜底', () => {
    expect(isActionPointSeries({key: 'ap', label: '别的名字'}, '行动力')).toBe(true)
    expect(isActionPointSeries({key: 'mileage', label: '行动力'}, '行动力')).toBe(true)
    expect(isActionPointSeries({key: 'mileage', label: '海里数'}, '行动力')).toBe(false)
  })
})
