/**
 * @fileoverview 工作台主题的内置实现：壳层布局、主导航与总览页的组装。
 */
import { Suspense } from 'react'
import { Link, NavLink, matchPath, useLocation, useNavigate } from 'react-router-dom'
import { Plus, WifiOff } from 'lucide-react'
import { useApp, useConnection } from '../app/context'
import { InstanceActions } from '../components/InstanceActions'
import { MonitorPanel } from '../components/MonitorPanel'
import { ResourceCards } from '../components/ResourceCards'
import { TaskQueue } from '../components/TaskQueue'
import { TaskSwitcher } from '../components/TaskSwitcher'
import { Button } from '../components/ui/button'
import { SchedulerWidget } from '../components/SchedulerWidget'
import { usePlugins } from '../plugins/context'
import { PluginLinks, PluginPanels } from '../plugins/views'
import type { OverviewBlock } from '../plugins/types'
import { ModernOverview, type OverviewViewProps } from '../pages/Overview'
import { PluginFrame } from '../plugins/PluginFrame'
import { useThemeComponent } from './context'
import { defineTheme, type NavigationProps, type ShellProps } from './definition'

// Hierarchy: scheduler and live monitor first, resources and queue second, navigation third.
// The shell owns scrolling; all colors, surfaces and controls inherit the shared theme tokens.
const styles = `
  .workbench-shell {display:grid; grid-template: "toolbar" auto "navigation" auto "content" minmax(0,1fr) / minmax(0,1fr); width:100%; height:var(--viewport-height, 100dvh); min-width:0; overflow:hidden; background:var(--bg); color:var(--text)}
  .workbench-shell[data-apu-navigation="bottom"] {grid-template: "toolbar" auto "content" minmax(0,1fr) "navigation" auto / minmax(0,1fr)}
  .workbench-shell .workbench-header {grid-area:toolbar; position:relative; z-index:30; border-bottom:1px solid var(--border); background:var(--surface)}
  .workbench-shell .workbench-toolbar {display:flex; flex-wrap:wrap; align-items:center; gap:12px; padding:12px 24px}
  .workbench-shell .workbench-instance {max-width:16rem; min-width:0; flex:1}
  .workbench-shell .workbench-nav-region {grid-area:navigation; background:var(--surface); overflow:auto; max-height:40dvh}
  .workbench-shell .workbench-navigation {display:flex; flex-wrap:wrap; gap:4px; padding:8px 24px}
  .workbench-shell .workbench-navigation a {display:inline-flex; align-items:center; gap:6px; min-height:36px; padding:8px 12px; border-radius:var(--radius); font-size:12px; color:var(--muted)}
  .workbench-shell .workbench-navigation a:hover {background:var(--surface-muted); color:var(--text)}
  .workbench-shell .workbench-navigation a.active {background:var(--accent-soft); color:var(--accent); font-weight:600}
  .workbench-shell .workbench-content {grid-area:content; min-width:0; min-height:0; width:100%; overflow:auto; overscroll-behavior:contain; padding:24px; scroll-padding:24px}
  .workbench-shell .workbench-overview {display:grid; gap:24px; min-width:0; max-width:1600px; margin:0 auto}
  .workbench-shell .workbench-content > * {min-width:0; max-width:100%}
  .workbench-shell .workbench-skip {position:fixed; top:8px; left:8px; z-index:100; transform:translateY(-200%); padding:12px; border-radius:var(--radius); background:var(--surface); color:var(--text)}
  .workbench-shell .workbench-skip:focus {transform:translateY(0)}
  @media (min-width:768px) {
    .workbench-shell[data-apu-navigation="left"] {grid-template: "toolbar toolbar" auto "navigation content" minmax(0,1fr) / minmax(10rem,14rem) minmax(0,1fr)}
    .workbench-shell[data-apu-navigation="right"] {grid-template: "toolbar toolbar" auto "content navigation" minmax(0,1fr) / minmax(0,1fr) minmax(10rem,14rem)}
    .workbench-shell:is([data-apu-navigation="left"],[data-apu-navigation="right"]) .workbench-nav-region {max-height:none}
    .workbench-shell:is([data-apu-navigation="left"],[data-apu-navigation="right"]) .workbench-navigation {flex-direction:column; padding:8px}
  }
  @media (max-width:767px) {
    .workbench-shell .workbench-toolbar {padding:12px; gap:8px}
    .workbench-shell .workbench-navigation {padding:0 12px 12px; gap:2px}
    .workbench-shell .workbench-navigation a {padding:6px 8px}
    .workbench-shell .workbench-content {padding:12px; scroll-padding:12px}
    .workbench-shell .workbench-overview {gap:16px}
    .workbench-shell .workbench-toolbar .task-picker {max-width:100%}
    .workbench-shell .workbench-toolbar .task-picker-menu {left:0; right:auto; max-width:calc(100vw - 24px)}
  }
`

/** 工作台默认的主导航链接组，覆盖全局页面、实例内页面与插件页面入口。 */
export function TopNavigation({instance, onNavigate, announcementUnread, updateAvailable}: NavigationProps) {
  const {ui} = useApp()
  const base = instance ? `/i/${encodeURIComponent(instance)}` : ''
  return <nav className="workbench-navigation" data-apu-component="navigation" aria-label={ui('nav.primary')}>
    {instance && <>
      <NavLink to={`${base}/overview`} onClick={onNavigate}>{ui('nav.overview')}</NavLink>
      <NavLink to={`${base}/statistics`} onClick={onNavigate}>{ui('nav.statistics')}</NavLink>
      <NavLink to={`${base}/resources`} onClick={onNavigate}>{ui('nav.resources')}</NavLink>
      <NavLink to={`${base}/stock-exchange`} onClick={onNavigate}>{ui('stock.name')}</NavLink>
    </>}
    <NavLink to="/announcement" onClick={onNavigate}>{ui('nav.announcement')}{announcementUnread && <span className="text-xs" aria-label={ui('nav.newBadge')}>●</span>}</NavLink>
    <NavLink to="/updater" onClick={onNavigate}>{ui('nav.updater')}{updateAvailable && <span className="text-xs">{ui('nav.newBadge')}</span>}</NavLink>
    <NavLink to="/interface" onClick={onNavigate}>{ui('nav.interface')}</NavLink>
    <NavLink to="/plugins" onClick={onNavigate}>{ui('nav.plugins')}</NavLink>
    <NavLink to="/remote" onClick={onNavigate}>{ui('nav.remote')}</NavLink>
    <NavLink to="/configs" onClick={onNavigate}>{ui('nav.configs')}</NavLink>
    <NavLink to="/settings" onClick={onNavigate}>{ui('nav.settings')}</NavLink>
    <a href="https://github.com/wess09/AzurPilot" target="_blank" rel="noreferrer" onClick={onNavigate}>{ui('nav.openSource')}</a>
    <PluginLinks instance={instance} onNavigate={onNavigate}/>
    {instance && <PluginLinks onNavigate={onNavigate}/>}
  </nav>
}

/** 工作台壳层：工具栏、实例切换、导航区与内容区；页面滚动由内容区承接。 */
export function WorkbenchShell({children, instance, pageTitle, onCreate, updateAvailable, announcementUnread}: ShellProps) {
  const {instances, ui} = useApp()
  const connection = useConnection()
  const location = useLocation()
  const navigate = useNavigate()
  const Navigation = useThemeComponent('Navigation', TopNavigation)
  const navigationPosition = usePlugins().theme?.manifest.theme?.navigation
  const suffix = matchPath('/i/:instance/*', location.pathname)?.params['*'] || 'overview'

  return <div className="workbench-shell" data-apu-component="shell" data-apu-navigation={navigationPosition}>
    <style>{styles}</style>
    <a className="workbench-skip" href="#main-content" onClick={event => {
      event.preventDefault()
      document.getElementById('main-content')?.focus()
    }}>{ui('nav.skipContent')}</a>
    <header className="workbench-header">
      <div className="workbench-toolbar">
        <Link to="/settings" className="text-base font-semibold" aria-label={`AzurPilot ${ui('nav.settings')}`}>AzurPilot</Link>
        <select className="workbench-instance" aria-label={ui('nav.instanceTabs')} value={instance ?? ''}
          onChange={event => {
            if (event.target.value) navigate(`/i/${encodeURIComponent(event.target.value)}/${suffix}${location.search}${location.hash}`)
          }}>
          <option value="" disabled>{ui('nav.instanceTabs')}</option>
          {instances.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}
        </select>
        <Button type="button" variant="outline" size="icon" aria-label={ui('instance.create')} title={ui('instance.create')}
          disabled={connection !== 'ready'} onClick={onCreate}><Plus aria-hidden="true"/></Button>
        {instance && <TaskSwitcher/>}
        <span className="min-w-0 break-words text-sm text-[var(--muted)]">{pageTitle}</span>
      </div>
      {connection !== 'ready' && <div role="status" className="flex items-center gap-2 bg-[var(--surface-muted)] px-3 py-2 text-sm"><WifiOff size={16} aria-hidden="true"/>{ui('connection.connecting')}</div>}
    </header>
    <div className="workbench-nav-region">
      <Suspense fallback={<TopNavigation instance={instance}/>}>
        <Navigation instance={instance} updateAvailable={updateAvailable} announcementUnread={announcementUnread}
          fallback={<TopNavigation instance={instance} updateAvailable={updateAvailable} announcementUnread={announcementUnread}/>}/>
      </Suspense>
    </div>
    <main id="main-content" tabIndex={-1} className="workbench-content">{children}</main>
  </div>
}

/** 主题总览入口：启用插件总览视图时渲染插件帧，否则回落内置的组合布局。 */
export function WorkbenchOverview(props: OverviewViewProps) {
  const {ui} = useApp()
  const theme = usePlugins().theme
  const entry = theme?.manifest.theme?.overviewView
  if (!theme || !entry) return <ComposedOverview {...props}/>
  return <div className="apu-overview-view" data-apu-component="overview">
    <PluginFrame key={theme.revision + ':' + props.instance} plugin={theme} entry={entry}
      title={ui('nav.overview')} instance={props.instance} fallback={<ModernOverview {...props}/>}/>
    <PluginPanels instance={props.instance}/>
  </div>
}

function ComposedOverview({instance, data, onData, selectedResources, onResourcesChange}: OverviewViewProps) {
  const {ui} = useApp()
  const SchedulerPanel = useThemeComponent('SchedulerPanel', SchedulerWidget)
  const order = usePlugins().theme?.manifest.theme?.overview ?? []
  const blocks: Record<OverviewBlock, React.ReactNode> = {
    resources: <ResourceCards resources={data.resources} selected={selectedResources}/>,
    scheduler: <SchedulerPanel instance={instance} data={data} onData={onData}/>,
    queue: <section className="panel p-4" aria-label={ui('scheduler.plan')}>
      <h2 className="m-0 mb-3 text-sm font-semibold">{ui('scheduler.plan')}</h2>
      <TaskQueue instance={instance} data={data} onData={onData}/>
    </section>,
    logs: <div className="apu-layout-wide apu-layout-logs"><MonitorPanel key={instance} instance={instance}/></div>,
    panels: <PluginPanels instance={instance}/>,
  }
  return <div className="workbench-overview apu-layout" data-apu-component="overview">
    <div className="flex min-w-0 items-center justify-between gap-3">
      <h1 className="m-0 min-w-0 break-words text-xl font-semibold">{instance}</h1>
      <InstanceActions resources={data.resources} selectedResources={selectedResources} onResourcesChange={onResourcesChange}/>
    </div>
    <div className="apu-layout-grid">
      {(order.includes('panels') ? order : [...order, 'panels'] as OverviewBlock[]).map(block =>
        <div key={block} data-apu-block={block} className={['resources', 'logs', 'panels'].includes(block) ? 'apu-layout-wide' : ''}>{blocks[block]}</div>)}
    </div>
  </div>
}

export default defineTheme({
  id: 'workbench',
  name: language => ({'zh-CN': '工作台', 'zh-TW': '工作台', 'en-US': 'Workbench', 'ja-JP': 'ワークベンチ'}[language]),
  components: {Shell: WorkbenchShell, Navigation: TopNavigation, Overview: WorkbenchOverview},
})
