/**
 * @fileoverview 调度器核心控制卡片与任务数量摘要组件。
 */

import { CalendarClock, Play, Square } from 'lucide-react'
import { useApp } from '../app/context'
import { usePlugins } from '../plugins/context'
import { pluginAsset } from '../plugins/types'
import { useSchedulerControls, type SchedulerPanelProps } from './useSchedulerControls'

export type { SchedulerPanelProps } from './useSchedulerControls'

/**
 * 调度器卡片：状态、三类任务计数与启停按钮。
 *
 * 旧版主题的总览页左列、其余主题的右栏、实例设置页的调度器栏都渲染它，
 * 三处共用同一份启停逻辑，保证「不带旧配置启动调度器」的排队屏障不会在某一处漏掉。
 */
export function SchedulerWidget(props: SchedulerPanelProps) {
  const {disabled, busy, isRunning, running, pending, waiting, toggleScheduler} = useSchedulerControls(props)
  const {ui} = useApp()
  const theme = usePlugins().theme
  const appearance = theme?.manifest.theme
  const icons = appearance?.icons
  const custom = appearance?.replaceSchedulerStyles
  const actionIcon = icons?.[isRunning ? 'scheduler.stop' : 'scheduler.start']

  return <section className={custom ? 'apu-scheduler' : 'scheduler-widget'} data-apu-component="scheduler" data-state={isRunning ? 'running' : 'stopped'} aria-label={ui('scheduler.title')}>
    <div className={custom ? undefined : 'scheduler-widget-heading'} data-apu-part="header">
      <div>{theme && icons?.['scheduler.title'] ? <img className="apu-scheduler-icon" src={pluginAsset(theme, icons['scheduler.title'])} alt=""/> : <CalendarClock size={18} strokeWidth={1.8}/>}<span>{ui('scheduler.title')}</span></div>
    </div>
    <div className={custom ? undefined : 'scheduler-stats'} data-apu-part="counts">
      <div className={custom ? undefined : 'running'} data-apu-part="running"><strong>{running}</strong><span>{ui('scheduler.running')}</span></div>
      <div className={custom ? undefined : 'pending'} data-apu-part="pending"><strong>{pending}</strong><span>{ui('scheduler.pending')}</span></div>
      <div className={custom ? undefined : 'waiting'} data-apu-part="waiting"><strong>{waiting}</strong><span>{ui('scheduler.waiting')}</span></div>
    </div>
    <button
      type="button"
      className={custom ? undefined : `button scheduler-toggle ${isRunning ? 'danger' : 'primary'}`}
      data-apu-part="toggle"
      onClick={toggleScheduler}
      disabled={disabled}
    >
      {theme && actionIcon ? <img className="apu-scheduler-icon" src={pluginAsset(theme, actionIcon)} alt=""/>
        : isRunning ? <Square size={11} fill="currentColor" strokeWidth={0}/> : <Play size={14}/>} {busy ? ui('scheduler.processing') : isRunning ? ui('scheduler.stop') : ui('scheduler.start')}
    </button>
  </section>
}
