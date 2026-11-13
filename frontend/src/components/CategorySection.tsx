/**
 * @fileoverview 统计页面单分类内容区组件。
 */

import { normalizeReport } from './statisticsData'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { api } from '../api/client'
import type { StatisticsReport } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { localizeReport } from './statisticsText'
import type { StatisticsCategory } from '../app/statisticsPrefs'

/** 单个页面的取数参数，与该页在布局文档里保存的一致。 */
interface CategoryParams {
  instance: string
  category: StatisticsCategory
  days: number
  month: string
  period: 'day' | 'week' | 'month'
  researchSeries: string
  lootTask: string
  includeSeries: boolean
}

/** 一段页面的内容区：自己取数、自己订阅统计事件，数据与渲染都交给调用方。 */
export function CategorySection({params, revision, onState, render}: {
  params: CategoryParams
  revision: number
  onState?: (state: {data?: StatisticsReport; error: string}) => void
  render: (data: StatisticsReport | undefined, error: string, page: StatisticsCategory) => ReactNode
}) {
  const {instance, category, days, month, period, researchSeries, lootTask, includeSeries} = params
  const researchScope = researchSeries === 'consumable' ? researchSeries : 'series'
  const connection = useConnection()
  const {language} = useApp()
  const [data, setData] = useState<StatisticsReport>()
  const [error, setError] = useState('')

  const request = useCallback(() => api.request('statistics.report', {
    instance, category, days, month, period,
    series: researchScope === 'series' ? Number(researchSeries) : 0,
    scope: researchScope,
    task: lootTask || null,
    include_series: includeSeries,
  }), [instance, category, days, month, period, researchScope, researchSeries, lootTask, includeSeries])

  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    let running = false
    let pending = false
    let timer: ReturnType<typeof setTimeout> | undefined
    setData(undefined); setError('')
    // 事件驱动的重取做合并：进行中的请求只记 pending，安静 300ms 后静默重取，
    // silent 模式失败不置 error，页面保住已有数据。
    const load = (silent: boolean) => {
      if (!active) return
      if (running) {pending = true; return}
      running = true
      void request().then(value => {
        if (active) {setData(normalizeReport(value)); setError('')}
      }).catch(reason => {
        if (active && !silent) setError(reason.message)
      }).finally(() => {
        running = false
        if (active && pending) {
          pending = false
          timer = setTimeout(() => load(true), 300)
        }
      })
    }
    const triggerUpdate = () => {
      if (running) {pending = true; return}
      clearTimeout(timer)
      timer = setTimeout(() => load(true), 300)
    }
    const off = api.onEvent(event => {
      const payload = event.data as {instance?: string} | undefined
      if (event.topic === 'statistics') {
        if (!payload?.instance || payload.instance === instance) triggerUpdate()
      }
    })
    load(false)
    return () => {
      active = false
      clearTimeout(timer)
      off()
    }
  }, [connection, instance, request, revision])

  // 后端标签是中文；在这里统一译成界面语言，下游的卡片、图表、表格和导出都用译文。
  const shown = useMemo(() => data && localizeReport(data, language), [data, language])

  useEffect(() => onState?.({data: shown, error}), [shown, error, onState])

  return <>{render(shown, error, category)}</>
}
