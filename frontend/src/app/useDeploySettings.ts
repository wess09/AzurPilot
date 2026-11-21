/**
 * @fileoverview 部署设置数据拉取与编辑队列管理 Hook。
 */

import { useSyncExternalStore } from 'react'
import { api } from '../api/client'
import type { Settings as SettingsData } from '../api/types'
import { editor } from '../config/editors'
import { useConnection } from './context'
import { usePageRead } from './usePageRead'

const readSettings = () => api.request('settings.get', {})
const remotePollInterval = (data: SettingsData | undefined, error: string) => error ? 5000 : data?.remote?.address ? 15000 : 3000

/**
 * 获取部署设置并管理其编辑队列。
 *
 * @param pollRemote 是否根据远程地址状态轮询更新。
 * @returns 设置数据、加载错误、编辑快照与共享队列。
 */
export function useDeploySettings(pollRemote = false) {
  const connection = useConnection()
  const queue = editor('deploy')
  const edits = useSyncExternalStore(queue.subscribe, queue.getSnapshot, queue.getSnapshot)

  const {data, error, reload} = usePageRead('settings', connection === 'ready', readSettings, pollRemote ? remotePollInterval : undefined)
  return {data, error, reload, edits, queue}
}
