/**
 * @fileoverview 统计页面单分类内容区组件。
 */

import { normalizeReport } from './statisticsData'
import { useCallback, useEffect, useState, type ReactNode } from 'react'

import { api } from '../api/client'
import type { StatisticsReport } from '../api/types'
import { useConnection } from '../app/context'
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

  useEffect(() => onState?.({data, error}), [data, error, onState])

  return <>{render(data, error, category)}</>
}
