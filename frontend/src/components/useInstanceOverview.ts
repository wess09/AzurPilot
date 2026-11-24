/**
 * @fileoverview 实例运行总览数据订阅 Hook。
 */
import { useCallback, useEffect, type SetStateAction } from 'react'
import { api } from '../api/client'
import type { Overview } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { usePageRead } from '../app/usePageRead'

/** 保留 [data, setData] API；第三项供页面控制器呈现加载错误。 */
export function useInstanceOverview(instance: string, enabled = true, {notifyErrors = true} = {}) {
  const connection = useConnection()
  const {notify} = useApp()
  const load = useCallback(() => api.request('overview.get', {instance}), [instance])
  const {data, error, reload, setData: publish} = usePageRead(instance, enabled && connection === 'ready', load)
  const setData = useCallback((value: SetStateAction<Overview | undefined>) => {
    if (typeof value !== 'function' && value && value.instance !== instance) return
    publish(previous => {
      const next = typeof value === 'function' ? value(previous) : value
      return next && next.instance !== instance ? previous : next
    })
  }, [instance, publish])
  useEffect(() => {if (error && notifyErrors) notify(error, true)}, [error, notify, notifyErrors])

  useEffect(() => {
    if (!enabled) return
    return api.onEvent(event => {
      if (event.topic !== 'overview') return
      const next = event.data as Overview
      if (next.instance === instance) setData(next)
    })
  }, [instance, enabled, setData])

  return [data, setData, error, reload] as const
}
