/**
 * @fileoverview 调度器启停控制 Hook：编辑器落盘屏障、连点防重与过期实例结果拦截。
 */

import { useCallback, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Overview as OverviewData } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { editor } from '../config/editors'

/** 调度器卡片与启停控制共用的属性：实例名、总览数据与总览回写。 */
export interface SchedulerPanelProps {
  instance: string
  data?: OverviewData
  onData: (data: OverviewData) => void
}

/**
 * 调度器启停逻辑：总览页、旧版主题等几处渲染同一张卡片，
 * 启停与计数统一从这里取，保证「不带旧配置启动调度器」的屏障不会在某一处漏掉。
 */
export function useSchedulerControls({instance, data, onData}: SchedulerPanelProps) {
  const connection = useConnection()
  const {notify, ui} = useApp()
  const [busy, setBusy] = useState(false)
  // 同步置位防重入：busy 状态要等重渲染才生效，同帧连点会绕过状态检查重复发请求。
  const busyRef = useRef(false)
  // 渲染期同步刷新：响应回来时实例已切换则丢弃，避免把旧实例的总览写进新实例的状态。
  const instanceRef = useRef(instance)
  instanceRef.current = instance

  const toggleScheduler = useCallback(() => {
    if (!data || busyRef.current || connection !== 'ready') return
    const running = data.status === 'running'
    busyRef.current = true
    setBusy(true)
    void (async () => {
      try {
        // 启动前等配置编辑器把未保存改动落盘（有未落盘的会抛错拦下）：防止带着旧配置启动调度器。
        if (!running) await editor(`config:${instance}`).settled()
        const next = await api.request(running ? 'scheduler.stop' : 'scheduler.start', {instance})
        if (instanceRef.current !== instance) return
        onData(next)
        notify(running ? ui('scheduler.stoppedNotice') : ui('scheduler.started'))
      } catch (error) {
        if (instanceRef.current === instance) notify((error as Error).message, true)
      } finally {
        busyRef.current = false
        setBusy(false)
      }
    })()
  }, [connection, data, instance, notify, onData, ui])

  const isRunning = data?.status === 'running'
  const running = data?.tasks.filter(task => task.state === 'running').length ?? 0
  const pending = data?.tasks.filter(task => task.state === 'pending').length ?? 0
  const waiting = data?.tasks.filter(task => task.state === 'waiting').length ?? 0
  const disabled = !data || busy || connection !== 'ready'

  return {disabled, busy, isRunning, running, pending, waiting, toggleScheduler}
}
