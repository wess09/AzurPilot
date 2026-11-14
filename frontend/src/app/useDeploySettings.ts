/**
 * @fileoverview 部署设置数据拉取与编辑队列管理 Hook。
 */

import { useEffect, useState, useSyncExternalStore } from 'react'
import { api } from '../api/client'
import type { Settings as SettingsData } from '../api/types'
import { editor } from '../config/editors'
import { useConnection } from './context'

/**
 * 获取部署设置并管理其编辑队列。
 *
 * @param pollRemote 是否根据远程地址状态轮询更新。
 * @returns 设置数据、加载错误、编辑快照与共享队列。
 */
export function useDeploySettings(pollRemote = false) {
  const [data, setData] = useState<SettingsData>()
  const [error, setError] = useState('')
  const connection = useConnection()
  const queue = editor('deploy')
  const edits = useSyncExternalStore(queue.subscribe, queue.getSnapshot, queue.getSnapshot)

  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    let timer: ReturnType<typeof setTimeout>
    const load = () => void api.request('settings.get', {})
      .then(data => {
        if (active) {
          setData(data)
          setError('')
          if (pollRemote) timer = setTimeout(load, data.remote?.address ? 15000 : 3000)
        }
      })
      .catch(error => {
        if (active) {
          setError(error.message)
          if (pollRemote) timer = setTimeout(load, 5000)
        }
      })
    load()
    return () => { active = false; clearTimeout(timer) }
  }, [connection, queue, pollRemote])

  return {data, error, edits, queue}
}
