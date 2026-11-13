/**
 * @fileoverview 版本更新状态与检查 Hook。
 */

import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { UpdateStatus } from '../api/types'
import { useConnection } from './context'

/**
 * 轮询版本更新状态：连接就绪后每 3 秒拉一次 updater.status，
 * 出错只记入 error、不终止轮询，连接断开重连后重新开始。
 * refresh 递增轮询代数，供「检查更新」入口手动触发一次重新拉取。
 */
export function useUpdater() {
  const connection = useConnection()
  const [data, setData] = useState<UpdateStatus>()
  const [error, setError] = useState('')
  const [generation, setGeneration] = useState(0)
  const refresh = useCallback(() => setGeneration(value => value + 1), [])
  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      try {
        const value = await api.request('updater.status', {})
        if (active) {setData(value); setError('')}
      } catch (error) {if (active) setError((error as Error).message)}
      if (active) timer = setTimeout(poll, 3000)
    }
    void poll()
    return () => {active = false; clearTimeout(timer)}
  }, [connection, generation])
  return {data, error, refresh}
}

/** useUpdater 的返回类型，经路由 Outlet 上下文传给 /updater 页消费。 */
export type UpdaterState = ReturnType<typeof useUpdater>
