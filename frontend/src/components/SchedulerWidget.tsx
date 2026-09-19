import { useState } from 'react'
import { CalendarClock, CirclePlay, Play, Square, TriangleAlert } from 'lucide-react'
import { api } from '../api/client'
import type { Overview } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { editor } from '../config/editors'

/**
 * 调度器卡片：状态、三类任务计数与启停按钮。
 *
 * 旧版主题下由运行总览页左列渲染，其余主题由右栏渲染，两处共用同一份启停逻辑，
 * 保证「不带旧配置启动调度器」的排队屏障不会在某一处漏掉。
 */
export function SchedulerWidget({instance, data, onData}: {instance: string; data?: Overview; onData: (data: Overview) => void}) {
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
      <div><CalendarClock size={17}/><span>{ui('scheduler.title')}</span></div>
      <span className={`scheduler-status ${data?.status === 'running' ? 'running' : ''}`}>
        {data?.status === 'running' ? <CirclePlay size={13}/> : data?.status === 'error' ? <TriangleAlert size={13}/> : <Square size={12}/>}
        {data?.status === 'running' ? ui('status.running') : data?.status === 'error' ? ui('scheduler.abnormal') : ui('scheduler.stopped')}
      </span>
    </div>
    <div className="scheduler-stats">
      <div><span>{ui('scheduler.running')}</span><strong>{running}</strong></div>
      <div><span>{ui('scheduler.pending')}</span><strong>{pending}</strong></div>
      <div><span>{ui('scheduler.waiting')}</span><strong>{waiting}</strong></div>
    </div>
    <button
      className={`button scheduler-toggle ${data?.status === 'running' ? 'danger' : 'primary'}`}
      onClick={toggleScheduler}
      disabled={!data || busy || connection !== 'ready'}
    >
      {data?.status === 'running' ? <Square size={14}/> : <Play size={14}/>} {busy ? ui('scheduler.processing') : data?.status === 'running' ? ui('scheduler.stop') : ui('scheduler.start')}
    </button>
  </section>
}
