/**
 * @fileoverview 应用顶层外壳组件与全局路由布局。
 */

import { PasswordInput, Select } from '../components/FormControls'
import { Input } from '../components/ui/input'
import { Suspense, useEffect, useRef, useState, useSyncExternalStore, type FormEvent, type ChangeEvent } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'
import { getLayout, subscribeLayout } from './layout'
import {NavHandle} from './NavHandle'
import {TabBarResizeHandle} from './TabBarResizeHandle'
import {SidebarResizeHandle} from './SidebarResizeHandle'
import { ArrowRight, Cat, ChartNoAxesCombined, CirclePause, CirclePlay, Download, ExternalLink, FileJson, Globe, LayoutDashboard, LoaderCircle, Megaphone, Menu, Palette, Puzzle, Settings2, WifiOff, X } from 'lucide-react'
import { api } from '../api/client'
import { editor } from '../config/editors'
import {bulkAction, bulkTargets} from './instanceBulk'
import { useApp, useConnection } from './context'
import { useAnnouncement } from './announcement'
import { ErrorBox, Loading, Modal } from '../components/ui'
import { MaterialInspector } from '../components/MaterialInspector'
import { ProjectLogo } from '../components/ProjectLogo'
import { taskLabel } from '../components/taskNavItems'
import { getMaterialInspector, subscribeMaterialInspector } from './materialInspectorState'
import { InstanceTabs } from '../components/InstanceTabs'
import { TaskNavTree } from '../components/TaskNavTree'
import { SidebarTransition } from '../components/SidebarTransition'

import { useIsDesktop } from './useIsDesktop'
import { TaskSwitcher } from '../components/TaskSwitcher'
import { useUpdater } from './updater'
import { usePageMotion } from './pageMotion'

import { useSystemNotifications } from './systemNotifications'
import { readLastPath, writeLastPath } from './topbarPrefs'
import { INSTANCE_NAME_PATTERN } from './instanceName'
import { useThemeComponent } from '../themes/context'
import { PluginLinks } from '../plugins/views'
import { PluginStyles, usePlugins } from '../plugins/context'
import type { NavigationProps, ShellProps } from '../themes/definition'

/*
 * 样式索引（混合分层 L2：外壳骨架宿主，样式横跨多域文件，无法 colocate）。
 * 外壳骨架类 app-shell / sidebar / topbar / primary-nav 全挂在本文件的 JSX 上，规则分布于：
 * - styles/layout.css           外壳骨架段：app-shell / sidebar / topbar / primary-nav / main-shell / breadcrumb / login-page / connection-banner / mobile-toggle
 * - styles/layout-modern.css    现代外壳段：modern-shell 下的 sidebar / topbar / modern-page-nav / modern-topbar-* / page-title-heading 视觉隐藏
 * - styles/theme-modern.css     现代主题段：对 primary-nav / sidebar / topbar / breadcrumb / skip-link 的主题覆写
 * - styles/topbar.css           顶栏域：topbar / app-shell / topbar-actions / filter-active 等顶栏与激活态规则
 * - styles/theme-primitives.css 主题契约消费层：外壳类绑定 --theme-* 变量的段落
 * 其余共享词汇类（button / icon-button / form-stack 等）由 buttons / forms / feedback 等域文件与主题系统统一提供，不逐处列出。
 */

/* 现代外壳下也要显示居中页名的顶层路由。 */
const PRIMARY_NAV_PATHS = ['/announcement', '/updater', '/interface', '/remote', '/configs', '/settings', '/plugins']
const SETUP_PATH = '/setup'

function ModernNavigation({instance, onNavigate, announcementUnread, updateAvailable}: NavigationProps) {
  const {ui} = useApp()
  const base = instance ? '/i/' + encodeURIComponent(instance) : ''
  return <nav className="primary-nav" data-apu-component="navigation" aria-label={ui('nav.primary')}>
    {instance ? <>
      <NavLink to={base + '/overview'} onClick={onNavigate}><LayoutDashboard size={17}/>{ui('nav.overview')}</NavLink>
      <NavLink to={base + '/statistics'} onClick={onNavigate}><ChartNoAxesCombined size={17}/>{ui('nav.statistics')}</NavLink>
      <NavLink to={base + '/stock-exchange'} onClick={onNavigate}><Cat size={17}/>{ui('stock.name')}</NavLink>
    </> : <>
      <NavLink to="/announcement" onClick={onNavigate}><Megaphone size={17}/>{ui('nav.announcement')}{announcementUnread && <span className="tiny-dot red"/>}</NavLink>
      <NavLink to="/updater" onClick={onNavigate}><Download size={17}/>{ui('nav.updater')}{updateAvailable && <span className="tiny-dot teal"/>}</NavLink>
      <NavLink to="/interface" onClick={onNavigate}><Palette size={17}/>{ui('nav.interface')}</NavLink>
      <NavLink to="/plugins" onClick={onNavigate}><Puzzle size={17}/>{ui('nav.plugins')}</NavLink>
      <NavLink to="/remote" onClick={onNavigate}><Globe size={17}/>{ui('nav.remote')}</NavLink>
      <NavLink to="/configs" onClick={onNavigate}><FileJson size={17}/>{ui('nav.configs')}</NavLink>
      <NavLink to="/settings" onClick={onNavigate}><Settings2 size={17}/>{ui('nav.settings')}</NavLink>
      <a className="nav-open-source" href="https://github.com/wess09/AzurPilot" target="_blank" rel="noreferrer" onClick={onNavigate}><ExternalLink size={17}/>{ui('nav.openSource')}</a>
    </>}
    <PluginLinks instance={instance} onNavigate={onNavigate}/>
  </nav>
}

/**
 * 创建实例的弹窗：支持选初始配置或从本机导入 JSON 配置文件。
 *
 * @param onClose 创建成功或取消后关闭弹窗的回调。
 * @param startWithImport 从「导入配置」入口进入时为 true，弹窗打开即拉取可导入配置列表。
 */
export function CreateInstance({onClose, startWithImport = false}: {onClose: () => void; startWithImport?: boolean}) {
  const [name, setName] = useState('')
  const [source, setSource] = useState('')
  const [importFile, setImportFile] = useState('')
  /* 导入候选按需拉取：点「导入配置」时才取，不在 dialog 打开时打接口。 */
  const [importState, setImportState] = useState<{loading: boolean; items: Array<{name: string; modified: number}>}>({loading: false, items: []})
  async function pickImport() {
    setImportState({loading: true, items: importState.items})
    try {
      const items = await api.request('instances.importable', {})
      setImportState({loading: false, items})
    } catch (error) { setImportState({loading: false, items: []}); setError((error as Error).message) }
  }
  /* 从「配置管理 → 导入配置」进来时，直接把可导入的配置文件列出来。 */
  useEffect(() => { if (startWithImport) void pickImport() }, [])

  /* 上传本机配置文件：读文件文本后上传，浏览器只给内容、给不了服务器路径。 */
  async function uploadImport(event: ChangeEvent<HTMLInputElement>) {
    const input = event.target
    const file = input.files?.[0]
    input.value = ''
    if (!file) return
    const stem = file.name.replace(/\.json$/i, '')
    setImportState({loading: true, items: importState.items})
    try {
      await api.request('instances.importConfig', {name: stem, content: await file.text()})
      const items = await api.request('instances.importable', {})
      setImportState({loading: false, items})
      chooseImport(stem)
    } catch (error) { setImportState({loading: false, items: importState.items}); setError((error as Error).message) }
  }
  /* 两处选择互斥：导入来的配置与「初始配置」二选一。 */
  function chooseImport(chosen: string) {
    setImportFile(chosen)
    if (chosen) setSource('')
    setName(current => current || chosen)
  }
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const {instances, refresh, notify, ui} = useApp()
  const navigate = useNavigate()
  const location = useLocation()
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      /* 后端会归一化首尾空白与尾点，导航用返回的规范名。 */
      const created = await api.request('instances.create', {name, source: source || null, import_file: importFile || null})
      await refresh(); onClose(); notify(ui('instance.created'))
      /* 新实例落在发起创建时所在的分区，从总览页创建就停在总览。 */
      navigate(`/i/${encodeURIComponent(created.instance)}/${location.pathname.split('/').slice(3).join('/') || 'overview'}`)
    } catch (error) { setError((error as Error).message) } finally { setBusy(false) }
  }
  return <Modal title={ui('instance.createTitle')} onClose={onClose}><form onSubmit={submit} className="form-stack">
    <p className="muted">{ui('instance.createHint')}</p>
    <label className="button secondary file-button" htmlFor="instance-import-file">{ui('instance.importPick')}<input id="instance-import-file" type="file" accept="application/json,.json" onChange={uploadImport}/></label>
    <button type="button" className="button secondary" disabled={importState.loading} onClick={pickImport}>{importState.loading ? ui('instance.importLoading') : ui('instance.importConfig')}</button>
    {importState.items.length > 0 && <label>{ui('instance.importSelect')}<Select value={importFile} onChange={event => chooseImport(event.target.value)}><option value="">{ui('instance.defaultConfig')}</option>{importState.items.map(item => <option key={item.name} value={item.name}>{item.name}</option>)}</Select><span className="muted">{ui('instance.importHint')}</span></label>}
    <label>{ui('instance.name')}<Input autoFocus required pattern={INSTANCE_NAME_PATTERN} value={name} onChange={event => setName(event.target.value)} placeholder={ui('instance.namePlaceholder')} maxLength={64}/></label>
    <label>{ui('instance.initialConfig')}<Select value={source} onChange={event => {setSource(event.target.value); setImportFile('')}}><option value="">{ui('instance.defaultConfig')}</option>{instances.map(item => <option key={item.name}>{item.name}</option>)}</Select></label>
    {error && <ErrorBox message={error}/>}
    <button className="button primary" disabled={busy}>{busy ? ui('instance.creating') : ui('instance.create')}<ArrowRight size={16}/></button>
  </form></Modal>
}

function Login() {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const {ui} = useApp()
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(''); setBusy(true)
    try { await api.login(password) } catch (error) { setError((error as Error).message) } finally { setBusy(false) }
  }
  return <div className="login-page"><div className="login-art"><ProjectLogo size={192}/><span>{ui('auth.slogan')}</span></div>
    <form onSubmit={submit} className="login-card"><ProjectLogo size={48} className="brand-mark" alt="AzurPilot"/><h1>{ui('auth.welcome')}</h1>
      <label htmlFor="password">{ui('auth.password')}</label><PasswordInput id="password" autoComplete="current-password" autoFocus required value={password} onChange={event => setPassword(event.target.value)}/>
      {error && <ErrorBox message={error}/>}
      <button className="button primary" disabled={busy}>{busy ? ui('auth.verifying') : ui('auth.enter')}<ArrowRight size={16}/></button>
      <small>{ui('auth.passwordHint')}</small>
    </form></div>
}

/**
 * 应用外壳：按连接状态分流登录页、引导页与主界面，组装侧栏、顶栏与路由出口，
 * 并按当前页面订阅后端事件主题。所有 Hook 都在早退 return 之前调用（见行内注释）。
 */
export function App() {
  const connection = useConnection()
  const {instancesLoaded, instances, schema, t, ui, notify, previewEnabled} = useApp()
  const {instance} = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const [creating, setCreating] = useState(false)
  // 只区分「全新打开」与「刷新 / 后退前进」：前者才回上次选中的实例。
  // 刷新时地址栏已经是用户要停留的页面，写进去就不再改。
  const freshOpen = useRef((performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined)?.type === 'navigate')
  const update = useUpdater()
  const announcement = useAnnouncement()
  usePageMotion()
  useSystemNotifications()
  const current = instances.find(item => item.name === instance)
  const subscribedInstance = current?.name ?? null
  const taskMatch = location.pathname.match(/\/task\/([^/]+)/)
  const currentTask = taskMatch ? taskMatch[1] : null
  const stockExchange = location.pathname.endsWith('/stock-exchange')
  const currentTaskLabel = currentTask ? taskLabel(currentTask, ui, t) : ''
  const pluginManager = location.pathname === '/plugins'
  const globalPlugin = location.pathname.startsWith('/plugins/')
  const activeSection = pluginManager ? ui('nav.plugins') : location.pathname === '/announcement' ? ui('nav.announcement') : location.pathname === '/settings' ? ui('nav.settings') : location.pathname === '/interface' ? ui('nav.interface') : location.pathname === '/remote' ? ui('nav.remote') : location.pathname === '/updater' ? ui('nav.updater') : location.pathname === '/configs' ? ui('nav.configs') : ''
  const Shell = useThemeComponent('Shell', ModernShell)
  const {plugins} = usePlugins()
  const {pluginId, pageId} = useParams()
  const pluginTitle = plugins.find(plugin => plugin.enabled && plugin.manifest.id === pluginId)
    ?.manifest.pages?.find(page => page.id === pageId)?.title
  const entryPath = instances.length > 0 ? `/i/${encodeURIComponent(instances[0].name)}/overview` : '/configs'
  const setup = location.pathname === SETUP_PATH
  const empty = instancesLoaded && instances.length === 0
  useEffect(() => {
    if (connection !== 'ready') return
    if (empty && !pluginManager && !globalPlugin) {
      if (!setup) navigate(SETUP_PATH, {replace: true})
    } else if ((setup && instancesLoaded) || (instancesLoaded && instance && !current)) {
      navigate(entryPath, {replace: true})
    }
  }, [connection, current, empty, entryPath, globalPlugin, instance, instancesLoaded, navigate, pluginManager, setup])
  /* 根路径只负责分流，不能覆盖上次停留的页面。 */
  useEffect(() => {
    if (!empty && (current || PRIMARY_NAV_PATHS.includes(location.pathname))) writeLastPath(location.pathname)
  }, [current, empty, location.pathname])
  useEffect(() => {
    if (location.pathname !== '/' || connection !== 'ready' || empty || !instancesLoaded) return
    const last = freshOpen.current ? readLastPath() : ''
    freshOpen.current = false
    const matched = last.match(/^\/i\/([^/]+)/)?.[1]
    /* 路由段是百分号编码的，含空格或中文的实例名解码后再与列表比对。 */
    let remembered
    try { remembered = matched ? decodeURIComponent(matched) : undefined } catch { remembered = undefined }
    const canRestore = PRIMARY_NAV_PATHS.includes(last) || instances.some(item => item.name === remembered)
    navigate(canRestore ? last : entryPath, {replace: true})
  }, [connection, empty, entryPath, instancesLoaded, instances, location.pathname, navigate])
  useEffect(() => {
    if (connection !== 'ready') return
    const topics: Array<'notifications' | 'instances' | 'launcher' | 'stock' | 'overview' | 'logs' | 'preview' | 'plugins'> = ['notifications', 'instances', 'plugins']
    if (['127.0.0.1', 'localhost', '[::1]'].includes(window.location.hostname)) topics.push('launcher')
    if (subscribedInstance) {
      if (stockExchange) topics.push('stock')
      else {
        topics.push('overview', 'logs')
        if (previewEnabled) topics.push('preview')
      }
    }
    void api.request('events.subscribe', {instance: subscribedInstance, topics}).catch(error => notify(error.message, true))
  }, [subscribedInstance, connection, notify, previewEnabled, stockExchange])
  // 「有可用更新」的角标，这里统一算一次。
  const updateAvailable = Boolean(update.data?.available)
  // 现代顶栏的第三列是居中的页面名：实例页写任务名，无实例时写导航项名。
  const pageTitle = pluginTitle ?? (instance
    ? currentTask ? currentTaskLabel : location.pathname.endsWith('/resources') ? ui('nav.resources') : location.pathname.endsWith('/statistics') ? ui('nav.statistics') : ui('nav.overview')
    : activeSection)
  if (connection === 'auth') return <Login/>
  if (setup || (empty && !pluginManager && !globalPlugin)) return <main className="instance-setup">{setup && empty && schema ? <Suspense fallback={<Loading/>}><Outlet/></Suspense> : <Loading/>}</main>
  const content = !schema || location.pathname === '/' || (instance && (!instancesLoaded || !current))
    ? <Loading/> : <Suspense fallback={<Loading/>}><Outlet context={update} key={instance ?? 'global'}/></Suspense>
  const props = {instance, pageTitle, onCreate: () => setCreating(true), updateAvailable, announcementUnread: announcement.unread}
  const ActiveShell = pluginManager ? ModernShell : Shell
  return <>
    {!pluginManager && <PluginStyles/>}
    <Suspense fallback={<ModernShell {...props}><Loading/></ModernShell>}>
      <ActiveShell {...props}>{content}</ActiveShell>
    </Suspense>
    {creating && <CreateInstance onClose={() => setCreating(false)}/>}
  </>
}

function ModernShell({children, instance, pageTitle, onCreate, updateAvailable, announcementUnread}: ShellProps) {
  const {instances, theme, notify, ui} = useApp()
  const connection = useConnection()
  const {pathname} = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)
  const closeDrawer = () => setMobileOpen(false)
  useEffect(() => {setMobileOpen(false)}, [pathname])
  const base = instance ? '/i/' + encodeURIComponent(instance) : ''
  const currentTask = pathname.match(/\/task\/([^/]+)/)?.[1]
  const pluginManager = pathname === '/plugins'
  const modernGlobalShell = PRIMARY_NAV_PATHS.includes(pathname)
  const modernShell = Boolean(instance) || modernGlobalShell
  const Navigation = useThemeComponent('Navigation', ModernNavigation)
  const brand = <><Link to="/settings" className="brand-title" aria-label={`AzurPilot ${ui('nav.settings')}`} onClick={closeDrawer}><ProjectLogo className="brand-logo"/><span>AzurPilot</span></Link>{updateAvailable && <Link className="update-notice sidebar-update-notice" to="/updater" aria-label={ui('nav.newVersion')} title={ui('nav.newVersion')}><span>{ui('nav.newBadge')}</span></Link>}</>
  const allowBulkToggle = useIsDesktop() && instances.length > 0
  const [bulkBusy, setBulkBusy] = useState(false)
  const bulk = bulkAction(instances)
  /* 一键启停：逐个实例串行处理，启动前先等该实例的配置落盘。 */
  const toggleAll = async () => {
    const targets = bulkTargets(instances, bulk)
    if (targets.length === 0) return
    setBulkBusy(true)
    let failed = 0
    for (const name of targets) {
      try {
        if (bulk === 'start') await editor(`config:${name}`).settled()
        await api.request(bulk === 'start' ? 'scheduler.start' : 'scheduler.stop', {instance: name})
      } catch (error) {
        failed += 1
        notify((error as Error).message, true)
      }
    }
    if (failed === 0) notify(ui(bulk === 'start' ? 'scheduler.started' : 'scheduler.stoppedNotice'))
    setBulkBusy(false)
  }
  const bulkToggle = !allowBulkToggle ? null : <button
    type="button"
    className="topbar-bulk-toggle icon-button"
    aria-label={ui(bulk === 'start' ? 'nav.startAll' : 'nav.stopAll')}
    title={ui(bulk === 'start' ? 'nav.startAll' : 'nav.stopAll')}
    disabled={bulkBusy}
    aria-busy={bulkBusy}
    onClick={toggleAll}
  >{bulkBusy ? <LoaderCircle size={17}/> : bulk === 'start' ? <CirclePlay size={17}/> : <CirclePause size={17}/>}</button>
  const tabNav = <>
    <span className="topbar-actions">
      {bulkToggle && <><span className="topbar-actions-hover"/><span className="topbar-actions-buttons">{bulkToggle}</span></>}
      <Link to="/settings" aria-label={ui('nav.settings')} title={ui('nav.settings')}><Settings2 size={16}/></Link>
    </span>
    <InstanceTabs onCreate={onCreate}/>
  </>
  const topbar = <header className="topbar">
    {modernShell && <div className="sidebar-brand modern-topbar-brand"><div className="sidebar-brand-left">{brand}</div></div>}
    <button className="mobile-toggle icon-button" aria-label={ui('nav.open')} onClick={() => setMobileOpen(true)}><Menu size={20}/></button>
    {modernShell
      ? <span className="modern-topbar-title">{pageTitle}</span>
      : <div className="breadcrumb with-tabs">{tabNav}{currentTask
        ? <Link className="breadcrumb-current" to={`${base}/task/${currentTask}`}><strong>{pageTitle}</strong></Link>
        : pageTitle && <strong className="breadcrumb-current">{pageTitle}</strong>}</div>}
    {!modernShell && <TabBarResizeHandle label={ui('nav.tabSize')}/>}
  </header>
  // 现代主题在居中页名下方显示实例标签与任务切换器。
  const pageNav = <div className="modern-page-nav">
    <div className="breadcrumb with-tabs">{tabNav}{currentTask && <TaskSwitcher/>}</div>
    <TabBarResizeHandle label={ui('nav.tabSize')}/>
  </div>
  /* shell 自己必须订阅：收起状态变了要重渲染才能加上 nav-collapsed 类（按钮订阅管不到这里）。 */
  const layout = useSyncExternalStore(subscribeLayout, getLayout, getLayout)
  /* 检视器停靠时整块画布要为它让出宽度，所以外壳自己订阅，靠类名驱动。 */
  const inspector = useSyncExternalStore(subscribeMaterialInspector, getMaterialInspector, getMaterialInspector)
  const hasDockedInspector = theme !== 'minimal' && inspector.open && inspector.docked && !inspector.minimized
  const PrimaryNavigation = pluginManager ? ModernNavigation : Navigation
  const navigationProps = {instance, onNavigate: closeDrawer, updateAvailable, announcementUnread}
  return <div
    className={`app-shell ${layout.sidebarCollapsed ? 'nav-collapsed' : ''} ${hasDockedInspector ? 'has-docked-inspector' : ''} ${currentTask ? 'task-config-shell' : ''} ${modernShell ? 'modern-shell' : ''} ${modernGlobalShell ? 'modern-global-shell' : ''} ${mobileOpen ? 'mobile-open' : ''}`}
    data-apu-component={pluginManager ? undefined : 'shell'}
  >
    <a className="skip-link" href="#main-content" onClick={event => {event.preventDefault(); document.getElementById('main-content')?.focus()}}>{ui('nav.skipContent')}</a>
    {modernShell && topbar}
    <NavHandle/>
    {/* 导航面板没有可编辑内容，右键默认菜单只会碍事：整块禁掉。 */}
    <aside className="sidebar" style={layout.sidebarWidth != null ? ({'--sidebar-width': `${layout.sidebarWidth}px`} as React.CSSProperties) : undefined} onContextMenu={event => event.preventDefault()}>
      <SidebarResizeHandle label="拖动调整侧边栏宽度（双击恢复默认）"/>
      {/* 现代主题把招牌放进顶栏，桌面端这一行隐藏；窄屏侧栏是抽屉，招牌回抽屉里。 */}
      <div className={`sidebar-brand ${modernShell ? 'modern-sidebar-actions' : ''}`.trim()}><div className="sidebar-brand-left">{brand}</div><button className="mobile-close icon-button" aria-label={ui('nav.close')} onClick={() => setMobileOpen(false)}><X size={18}/></button></div>
      <SidebarTransition viewKey={instance ? `instance:${instance}` : 'global'}>
        <Suspense fallback={<ModernNavigation {...navigationProps}/>}>
          <PrimaryNavigation {...navigationProps} fallback={<ModernNavigation {...navigationProps}/>}/>
        </Suspense>
        {instance && <TaskNavTree onNavigate={closeDrawer}/>}
      </SidebarTransition>
    </aside>
    <div className="main-shell">
      {!modernShell && topbar}
      {modernShell && pageNav}
      {connection !== 'ready' && <div className="connection-banner" role="status"><WifiOff size={16}/>{ui('connection.connecting')}</div>}
      <main id="main-content" tabIndex={-1}>{children}</main>
    </div>
    {theme !== 'minimal' && <MaterialInspector/>}
  </div>
}
