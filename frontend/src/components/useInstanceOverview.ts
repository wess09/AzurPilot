/**
 * @fileoverview 实例运行总览数据订阅 Hook。
 */
import { useCallback, useEffect, useRef, useState, type SetStateAction } from 'react'
import { api } from '../api/client'
import type { Overview } from '../api/types'
import { useApp, useConnection } from '../app/context'

/** 保留 [data, setData] API；第三项供页面控制器呈现加载错误。 */
export function useInstanceOverview(instance: string, enabled = true, {notifyErrors = true} = {}) {
  const connection = useConnection()
  const {notify} = useApp()
  const currentInstance = useRef(instance)
  currentInstance.current = instance
  const [snapshot, setSnapshot] = useState<{instance: string; data?: Overview; error: string}>(() => ({instance, error: ''}))
  const setData = useCallback((value: SetStateAction<Overview | undefined>) => {
    if (currentInstance.current !== instance) return
    setSnapshot(previous => {
      const data = typeof value === 'function' ? value(previous.instance === instance ? previous.data : undefined) : value
      if (data && data.instance !== instance) return previous
      return {instance, data, error: ''}
    })
  }, [instance])

  useEffect(() => {
    if (!enabled || connection !== 'ready') return
    let active = true
    void api.request('overview.get', {instance})
      .then(value => { if (active) setData(value) })
      .catch(error => {
        if (!active) return
        const message = (error as Error).message
        setSnapshot(previous => ({instance, data: previous.instance === instance ? previous.data : undefined, error: message}))
        if (notifyErrors) notify(message, true)
      })
    return () => { active = false }
  }, [connection, instance, notify, enabled, notifyErrors, setData])

  useEffect(() => {
    if (!enabled) return
    return api.onEvent(event => {
      if (event.topic !== 'overview') return
      const next = event.data as Overview
      if (next.instance === instance) setData(next)
    })
  }, [instance, enabled, setData])

  return [snapshot.instance === instance ? snapshot.data : undefined, setData, snapshot.instance === instance ? snapshot.error : ''] as const
}
