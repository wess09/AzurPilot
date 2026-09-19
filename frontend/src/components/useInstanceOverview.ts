import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Overview } from '../api/types'
import { useApp, useConnection } from '../app/context'

/**
 * 订阅实例总览数据：连上后拉取一次，之后由 overview 事件增量刷新。
 *
 * 旧版实例页的左列（调度器 + 任务计划）与右栏渲染的是同一份数据，
 * 两处共用本 Hook，避免各自写一遍订阅逻辑。`enabled` 为假时完全不请求，
 * 供只在旧版主题下才需要这份数据的页面使用。
 */
export function useInstanceOverview(instance: string, enabled = true) {
  const connection = useConnection()
  const {notify} = useApp()
  const [data, setData] = useState<Overview>()

  useEffect(() => {
    if (!enabled || connection !== 'ready') return
    let active = true
    void api.request('overview.get', {instance})
      .then(value => { if (active) setData(value) })
      .catch(error => notify((error as Error).message, true))
    return () => { active = false }
  }, [connection, instance, notify, enabled])

  useEffect(() => {
    if (!enabled) return
    return api.onEvent(event => {
      if (event.topic !== 'overview') return
      const next = event.data as Overview
      if (next.instance === instance) setData(next)
    })
  }, [instance, enabled])

  return [data, setData] as const
}
