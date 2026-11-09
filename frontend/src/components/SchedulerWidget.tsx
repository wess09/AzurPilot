/**
 * @fileoverview 调度器核心控制卡片与任务数量摘要组件。
 */

import type { ReactNode } from 'react'
import { useState } from 'react'
import { CalendarClock, Play, Square } from 'lucide-react'
import { api } from '../api/client'
import type { Overview } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { editor } from '../config/editors'

/**
 * 调度器卡片：状态、三类任务计数与启停按钮。
 *
 * 旧版主题的总览页左列、其余主题的右栏、实例设置页的调度器栏都渲染它，
 * 三处共用同一份启停逻辑，保证「不带旧配置启动调度器」的排队屏障不会在某一处漏掉。
 */
export function SchedulerWidget({instance, data, onData, action}: {instance: string; data?: Overview; onData: (data: Overview) => void; action?: ReactNode}) {
  const connection = useConnection()
  const {notify, ui} = useApp()
  const [busy, setBusy] = useState(false)

  async function toggleScheduler() {
    if (!data) return
    setBusy(true)
    try {
      if (data.status !== 'running') await editor(`config:${instance}`).settled()
      const next = await api.request(data.status === 'running' ? 'scheduler.stop' : 'scheduler.start', {instance})
      onData(next)
      notify(data.status === 'running' ? ui('scheduler.stoppedNotice') : ui('scheduler.started'))
    } catch (error) {
      notify((error as Error).message, true)
    } finally {
      setBusy(false)
    }
  }

  const running = data?.tasks.filter(task => task.state === 'running').length ?? 0
  const pending = data?.tasks.filter(task => task.state === 'pending').length ?? 0
  const waiting = data?.tasks.filter(task => task.state === 'waiting').length ?? 0

  return <section className="scheduler-widget" aria-label={ui('scheduler.title')}>
    <div className="scheduler-widget-heading">
      <div>{action ?? <CalendarClock size={18} strokeWidth={1.8}/>}<span>{ui('scheduler.title')}</span></div>
    </div>
    <div className="scheduler-stats">
      <div className="running"><strong>{running}</strong><span>{ui('scheduler.running')}</span></div>
      <div className="pending"><strong>{pending}</strong><span>{ui('scheduler.pending')}</span></div>
      <div className="waiting"><strong>{waiting}</strong><span>{ui('scheduler.waiting')}</span></div>
    </div>
    <button
      className={`button scheduler-toggle ${data?.status === 'running' ? 'danger' : 'primary'}`}
      onClick={toggleScheduler}
      disabled={!data || busy || connection !== 'ready'}
    >
      {data?.status === 'running' ? <Square size={11} fill="currentColor" strokeWidth={0}/> : <Play size={14}/>} {busy ? ui('scheduler.processing') : data?.status === 'running' ? ui('scheduler.stop') : ui('scheduler.start')}
    </button>
  </section>
}
