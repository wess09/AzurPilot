/**
 * @fileoverview 统计页面单分类内容区组件。
 */

import { normalizeReport } from './statisticsData'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from 'react'

import { api } from '../api/client'
import type { StatisticsReport } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { localizeReport } from './statisticsText'
import type { StatisticsCategory } from '../app/statisticsPrefs'
import { usePageRead } from '../app/usePageRead'

/** 单个页面的取数参数，与该页在布局文档里保存的一致。 */
interface CategoryParams {
  instance: string
  category: StatisticsCategory
  days: number
  month: string
  period: 'day' | 'week' | 'month'
  /** 研究系列取数键：'consumable' 表示消耗品口径，其余为具体系列编号字符串。 */
  researchSeries: string
  /** 掉落任务名，空串表示不过滤。 */
  lootTask: string
  /** 是否在响应里附带系列明细。 */
  includeSeries: boolean
}

/** 一段页面的内容区：自己取数、自己订阅统计事件，数据与渲染都交给调用方。 */
export function CategorySection({params, revision, onState}: {
  params: CategoryParams
  revision: number
  onState: (page: StatisticsCategory, data?: StatisticsReport, error?: string) => void
}) {
  const {instance, category, days, month, period, researchSeries, lootTask, includeSeries} = params
  const researchScope = researchSeries === 'consumable' ? researchSeries : 'series'
  const connection = useConnection()
  const {language} = useApp()
  const request = useCallback(async () => normalizeReport(await api.request('statistics.report', {
    instance, category, days, month, period,
    series: researchScope === 'series' ? Number(researchSeries) : 0,
    scope: researchScope,
    task: lootTask || null,
    include_series: includeSeries,
  })), [instance, category, days, month, period, researchScope, researchSeries, lootTask, includeSeries])
  const identity = JSON.stringify([instance, category, days, month, period, researchSeries, lootTask, includeSeries])
  const {data, error, reload} = usePageRead(identity, connection === 'ready', request)
  const lastRead = useRef({identity, revision})
  useEffect(() => {
    if (lastRead.current.identity === identity && lastRead.current.revision !== revision) reload()
    lastRead.current = {identity, revision}
  }, [identity, reload, revision])

  useEffect(() => {
    if (connection !== 'ready') return
    let timer: ReturnType<typeof setTimeout> | undefined
    const off = api.onEvent(event => {
      const payload = event.data as {instance?: string} | undefined
      if (event.topic !== 'statistics' || (payload?.instance && payload.instance !== instance)) return
      clearTimeout(timer)
      timer = setTimeout(() => void reload({silent: true}), 300)
    })
    return () => {
      clearTimeout(timer)
      off()
    }
  }, [connection, instance, reload])

  // 后端标签是中文；在这里统一译成界面语言，下游的卡片、图表、表格和导出都用译文。
  const shown = useMemo(() => data && localizeReport(data, language), [data, language])

  useLayoutEffect(() => onState(category, shown, error), [category, shown, error, onState])

  return null
}
