/**
 * @fileoverview 旧版实例视图左侧调度器与任务列表面板组件。
 */

import type { ReactNode } from 'react'
import type { Overview } from '../api/types'
import { useApp } from '../app/context'
import { SchedulerWidget } from './SchedulerWidget'
import { TaskQueue } from './TaskQueue'

/**
 * 旧版实例页的左列：调度器 + 任务计划。
 *
 * `children` 插在调度器与任务计划之间，供总览页放「统计界面」入口。
 */
export function LegacyRail({instance, data, onData, children}: {instance: string; data?: Overview; onData: (data: Overview) => void; children?: ReactNode}) {
  const {ui} = useApp()
  return <div className="instance-page-rail">
    <SchedulerWidget instance={instance} data={data} onData={onData}/>
    {children}
    <section className="rail-schedule" aria-label={ui('scheduler.plan')}>
      <TaskQueue instance={instance} data={data}/>
    </section>
  </div>
}
