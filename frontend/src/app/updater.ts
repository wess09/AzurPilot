/**
 * @fileoverview 版本更新状态与检查 Hook。
 */

import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { UpdateStatus } from '../api/types'
import { useConnection } from './context'

/**
 * 轮询版本更新状态并支持手动刷新。
 *
 * 连接就绪后每 3 秒拉取一次 `updater.status`，出错只记录错误且不终止轮询。
 * @returns 更新状态、错误信息与触发重新拉取的函数。
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
