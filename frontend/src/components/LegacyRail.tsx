import type { ReactNode } from 'react'
import { Clock3 } from 'lucide-react'
import type { Overview } from '../api/types'
import { useApp } from '../app/context'
import { SchedulerWidget } from './SchedulerWidget'
import { TaskQueue } from './TaskQueue'

/**
 * 旧版实例页的左列：调度器 + 任务计划。
 *
 * 旧 WebUI 把这两块放在页面左列，所以总览、任务配置、资源统计共用同一列，
 * 右栏在旧版主题下不再渲染（见 app/theme.ts 的 showsRightRail）。
 * `children` 插在调度器与任务计划之间，供总览页放「统计界面」入口。
 */
export function LegacyRail({instance, data, onData, children}: {instance: string; data?: Overview; onData: (data: Overview) => void; children?: ReactNode}) {
  const {ui} = useApp()
  return <div className="instance-page-rail">
    <SchedulerWidget instance={instance} data={data} onData={onData}/>
    {children}
    <section className="rail-schedule" aria-label={ui('scheduler.plan')}>
      <div className="rail-section-heading">
        <div><Clock3 size={15}/><span>{ui('scheduler.plan')}</span></div>
        <span>{data?.tasks.length ?? 0}</span>
      </div>
      <TaskQueue instance={instance} data={data}/>
    </section>
  </div>
}
