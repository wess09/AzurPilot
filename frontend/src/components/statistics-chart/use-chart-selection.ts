/**
 * @fileoverview 图表选取与筛选状态：选中系列、图表类型、坐标轴、采样粒度与时间范围。
 * 从 StatisticsChart.tsx 原 130-168 行提取，纯搬迁未改动。
 */
import { useCallback, useState } from 'react'
import {
  readStatisticsPrefs,
  updateStatisticsPrefs,
  setSelectedKeysForCategory,
  getSelectedKeysForCategory,
  type ChartMode,
  type ChartAxisMode,
} from '../../app/statisticsPrefs'
import type {StatSeries} from '../../api/types'

/** 管理图表的选中系列与展示偏好，偏好值按类目持久化到 localStorage。 */
export function useChartSelection({category, series}: {category: string; series: StatSeries[]}) {
  const [selectedKeys, setSelectedKeysState] = useState<string[]>(() => {
    const remembered = getSelectedKeysForCategory(category, series)
    if (remembered.length > 0) return remembered
    const active = series.find(item => item.points.length)?.key ?? series[0]?.key
    return active ? [active] : []
  })

  const setSelectedKeys = useCallback((updater: string[] | ((prev: string[]) => string[])) => {
    setSelectedKeysState(prev => {
      const next = typeof updater === 'function' ? updater(prev) : updater
      setSelectedKeysForCategory(category, next)
      return next
    })
  }, [category])

  const [mode, setModeState] = useState<ChartMode>(() => readStatisticsPrefs().chartMode)
  const setMode = useCallback((next: ChartMode) => {
    setModeState(next)
    updateStatisticsPrefs({chartMode: next})
  }, [])

  const [axisMode, setAxisModeState] = useState<ChartAxisMode>(() => readStatisticsPrefs().chartAxisMode)
  const setAxisMode = useCallback((next: 'separate' | 'unified') => {
    setAxisModeState(next)
    updateStatisticsPrefs({chartAxisMode: next})
  }, [])

  const [bucket, setBucketState] = useState(() => {
    const saved = readStatisticsPrefs().bucket
    const activeMode = readStatisticsPrefs().chartMode
    return activeMode === 'candlestick' && saved === 0 ? 60 : saved
  })
  const setBucket = useCallback((next: number) => {
    setBucketState(next)
    updateStatisticsPrefs({bucket: next})
  }, [])

  const [from, setFrom] = useState(() => readStatisticsPrefs().rangeFrom)
  const [to, setTo] = useState(() => readStatisticsPrefs().rangeTo)

  return {selectedKeys, setSelectedKeys, mode, setMode, axisMode, setAxisMode, bucket, setBucket, from, setFrom, to, setTo}
}
