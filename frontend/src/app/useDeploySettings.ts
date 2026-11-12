/**
 * @fileoverview 部署设置数据拉取与编辑队列管理 Hook。
 */

import { useEffect, useState, useSyncExternalStore } from 'react'
import { api } from '../api/client'
import type { Settings as SettingsData } from '../api/types'
import { editor } from '../config/editors'
import { useConnection } from './context'

/**
 * 部署设置的取数与编辑队列。
 *
 * 三个设置页共用同一份逻辑与同一条 `deploy` 队列：队列按作用域取单例，
 * 页面切换不会丢掉未确认的输入。
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
    // 先记下读取前已确认的编辑；数据到手后 reconcile 只清这批，读取期间的新输入仍由队列保护。
    const confirmed = queue.confirmed()
    let timer: ReturnType<typeof setTimeout>
    const load = () => void api.request('settings.get', {})
      .then(data => {
        if (active) {
          setData(data)
          setError('')
          queue.reconcile(confirmed)
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
