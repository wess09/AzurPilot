/**
 * 从 Statistics.tsx 原 171-206 行提取，纯搬迁未改动。
 * 统计页筛选偏好：分类、时间窗口与大世界/科研视图，修改时同步写回本地偏好。
 */
import { useCallback, useRef, useState } from 'react'
import { readStatisticsPrefs, updateStatisticsPrefs } from '../../app/statisticsPrefs'
import type { Category } from './shared'

export function useStatisticsPrefs() {
  const initialPrefs = useRef(readStatisticsPrefs()).current
  const [category, setCategoryState] = useState<Category>(initialPrefs.category)
  const [days, setDaysState] = useState(initialPrefs.days)
  const [month, setMonth] = useState(() => {const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`})
  const [period, setPeriodState] = useState<'day' | 'week' | 'month'>(initialPrefs.period)
  // 科研视图：'1'~'9' = 各期（默认 9 期），'consumable' = 心智/物资。
  // 后者不分期：心智与物资各期混着出，只有彩装备与舰船图纸绑定期数。
  const [researchSeries, setResearchSeriesState] = useState(initialPrefs.researchSelect)
  // 大世界掉落视图：'' = 全部大世界任务，其余是任务标识（选项由后端 taskOptions 给出）。
  const [lootTask, setLootTaskState] = useState(initialPrefs.lootTask)
  const [zeroBase, setZeroBaseState] = useState(initialPrefs.chartZeroBase)

  const setCategory = useCallback((next: Category) => {
    setCategoryState(next)
    updateStatisticsPrefs({category: next})
  }, [])
  const setDays = useCallback((next: number) => {
    setDaysState(next)
    updateStatisticsPrefs({days: next})
  }, [])
  const setPeriod = useCallback((next: 'day' | 'week' | 'month') => {
    setPeriodState(next)
    updateStatisticsPrefs({period: next})
  }, [])
  const setResearchSeries = useCallback((next: string) => {
    setResearchSeriesState(next)
    updateStatisticsPrefs({researchSelect: next})
  }, [])
  const setLootTask = useCallback((next: string) => {
    setLootTaskState(next)
    updateStatisticsPrefs({lootTask: next})
  }, [])
  const setZeroBase = useCallback((next: boolean) => {
    setZeroBaseState(next)
    updateStatisticsPrefs({chartZeroBase: next})
  }, [])

  return {category, days, month, period, researchSeries, lootTask, zeroBase, setCategory, setDays, setMonth, setPeriod, setResearchSeries, setLootTask, setZeroBase}
}
