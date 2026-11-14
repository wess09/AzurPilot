/**
 * @fileoverview 总览页调度面板的插件接管入口：启用主题声明 scheduler 槽位时改渲染插件帧。
 */
import { useApp } from '../app/context'
import { SchedulerWidget } from '../components/SchedulerWidget'
import { useSchedulerControls, type SchedulerPanelProps } from '../components/useSchedulerControls'
import { PluginFrame } from './PluginFrame'
import { usePlugins } from './context'

/** 调度面板槽位：插件视图不可用或未声明时回落内置 SchedulerWidget。 */
export function PluginScheduler(props: SchedulerPanelProps) {
  const theme = usePlugins().theme
  const entry = theme?.manifest.theme?.scheduler
  if (!theme || !entry) return <SchedulerWidget {...props}/>
  return <ActiveScheduler key={theme.revision + ':' + props.instance} plugin={theme} entry={entry} props={props}/>
}

function ActiveScheduler({plugin, entry, props}: {
  plugin: NonNullable<ReturnType<typeof usePlugins>['theme']>
  entry: string
  props: SchedulerPanelProps
}) {
  const {ui} = useApp()
  const {toggleScheduler, ...state} = useSchedulerControls(props)
  return <section className="apu-scheduler" data-apu-component="scheduler" aria-label={ui('scheduler.title')}>
    <PluginFrame plugin={plugin} entry={entry} title={ui('scheduler.title')} instance={props.instance}
      scheduler={{state, toggle: toggleScheduler, disabled: state.disabled}}
      fallback={<SchedulerWidget {...props}/>}/>
  </section>
}
