/**
 * @fileoverview 实例运行总览数据订阅 Hook。
 */

import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Overview } from '../api/types'
import { useApp, useConnection } from '../app/context'

/**
 * 订阅实例总览数据：连上后拉取一次，之后由 overview 事件增量刷新。
 *
 * 右栏与实例设置页的调度器栏用它取数；`enabled` 为假时完全不请求。
 * data 为 undefined 表示还没取到首份数据，调用方按加载态渲染。
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
