import { useEffect, useState } from 'react'
import { Clock3, X } from 'lucide-react'
import { api } from '../api/client'
import type { Overview } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { SchedulerWidget } from './SchedulerWidget'
import { TaskQueue } from './TaskQueue'

/** 右侧栏：调度器与任务计划。旧版主题的总览页改用页内两列，本组件只在其余页面渲染。 */
export function RightRail({instance, onMobileClose}: {instance: string; onMobileClose: () => void}) {
  const connection = useConnection()
  const {notify, ui} = useApp()
  const [data, setData] = useState<Overview>()

  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    void api.request('overview.get', {instance})
      .then(value => { if (active) setData(value) })
      .catch(error => notify((error as Error).message, true))
    return () => { active = false }
  }, [connection, instance, notify])

  useEffect(() => api.onEvent(event => {
    if (event.topic !== 'overview') return
    const next = event.data as Overview
    if (next.instance === instance) setData(next)
  }), [instance])

  return <aside className="right-rail" id="right-rail-menu" aria-label={ui('scheduler.rail')}>
    <div className="right-rail-header">
      <div>
        <span className="right-rail-eyebrow">{ui('scheduler.workspace')}</span>
        <strong>{instance}</strong>
      </div>
      <button className="mobile-rail-close icon-button" aria-label={ui('nav.closeRail')} onClick={onMobileClose}><X size={18}/></button>
    </div>

    <SchedulerWidget instance={instance} data={data} onData={setData}/>

    <section className="rail-schedule" aria-label={ui('scheduler.plan')}>
      <div className="rail-section-heading">
        <div><Clock3 size={15}/><span>{ui('scheduler.plan')}</span></div>
        <span>{data?.tasks.length ?? 0}</span>
      </div>
      <TaskQueue instance={instance} data={data} onNavigate={onMobileClose}/>
    </section>
  </aside>
}
