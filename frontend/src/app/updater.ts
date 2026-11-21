/**
 * @fileoverview 版本更新状态与检查 Hook。
 */

import { api } from '../api/client'
import { useConnection } from './context'
import { usePageRead } from './usePageRead'

const readStatus = () => api.request('updater.status', {})
const statusPollInterval = () => 3000

/**
 * 轮询版本更新状态并支持手动刷新。
 *
 * 连接就绪后每 3 秒拉取一次 `updater.status`，出错只记录错误且不终止轮询。
 * @returns 更新状态、错误信息与触发重新拉取的函数。
 */
export function useUpdater() {
  const connection = useConnection()
  const {data, error, reload: refresh} = usePageRead('updater', connection === 'ready', readStatus, statusPollInterval)
  return {data, error, refresh}
}

/** useUpdater 的返回类型，经路由 Outlet 上下文传给 /updater 页消费。 */
export type UpdaterState = ReturnType<typeof useUpdater>
