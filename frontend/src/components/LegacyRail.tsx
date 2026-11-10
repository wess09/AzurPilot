/**
 * @fileoverview 旧版实例视图左侧调度器与任务列表面板组件。
 */

import type { ReactNode } from 'react'
import type { Overview } from '../api/types'
import { useApp } from '../app/context'
import { SchedulerWidget } from './SchedulerWidget'
import { TaskQueue } from './TaskQueue'

/**
 * 调度器 + 任务计划这一列的唯一装配点。
 *
 * 总览页左列、任务设置页右栏都用它，只是外壳类名不同（`className`）：
 * 里面的启停逻辑、队列刷新、右键菜单都只有这一份，别处不要再自己拼
 * `SchedulerWidget` + `TaskQueue`。`children` 插在两者之间，供总览页放「统计界面」入口。
 */
export function LegacyRail({instance, data, onData, children}: {instance: string; data?: Overview; onData: (data: Overview) => void; children?: ReactNode}) {
  const {ui} = useApp()
  return <div className="instance-page-rail" onContextMenu={event => event.preventDefault()}>
    <SchedulerWidget instance={instance} data={data} onData={onData}/>
    {children}
    <section className="rail-schedule" aria-label={ui('scheduler.plan')}>
      <TaskQueue instance={instance} data={data} onData={onData}/>
    </section>
  </div>
}
