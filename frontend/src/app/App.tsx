/**
 * @fileoverview 应用顶层外壳组件与全局路由布局。
 */

import { PasswordInput, Select } from '../components/FormControls'
import { useEffect, useRef, useState, useSyncExternalStore, type FormEvent, type MouseEvent, type ChangeEvent } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'
import { getLayout, subscribeLayout } from './layout'
import {usesMaterial} from './theme'
import {NavHandle} from './NavHandle'
import {TabBarResizeHandle} from './TabBarResizeHandle'
import {SidebarResizeHandle} from './SidebarResizeHandle'
import { ArrowRight, CalendarClock, Cat, ChartNoAxesCombined, CirclePause, CirclePlay, Code2, Download, ExternalLink, FileJson, Globe, LayoutDashboard, LoaderCircle, Megaphone, Menu, Palette, Settings2, WifiOff, X } from 'lucide-react'
import { api } from '../api/client'
import { editor } from '../config/editors'
import {bulkAction, bulkTargets} from './instanceBulk'
import { useApp, useConnection } from './context'
import { useAnnouncement } from './announcement'
import { ErrorBox, Loading, Modal } from '../components/ui'
import { GlassMaterial } from '../components/GlassMaterial'
import { MaterialInspector } from '../components/MaterialInspector'
import { ProjectLogo } from '../components/ProjectLogo'
import { FLEET_ANALYSIS, FLEET_SWITCH, FLEET_TRAINING, FLEET_LEVEL_TRAINING, FLEET_AFFINITY_TRAINING, FLEET_EQUIPMENT, FLEET_ROTATION, SCHEDULER_EDITOR, taskLabel } from '../components/taskNavItems'
import { getMaterialInspector, subscribeMaterialInspector } from './materialInspectorState'
import { InstanceTabs } from '../components/InstanceTabs'
import { RightRail } from '../components/RightRail'
import { CompactScrollbars } from '../components/CompactScrollbars'
import { TaskNav } from '../components/TaskNav'
import { SidebarTransition } from '../components/SidebarTransition'

import { useIsDesktop } from '../components/TaskNav'
import { TaskSwitcher } from '../components/TaskSwitcher'
import { useUpdater } from './updater'
import { usePageMotion } from './pageMotion'
import { useGlassPointerLight } from './pointerLight'
import { recordDevLogoClick } from './devMode'
import { useDevOverride } from './devOverride'
import { useSystemNotifications } from './systemNotifications'
import { usesLegacyLayout, usesLegacyShell, showsRightRail } from './theme'
import { readLastPath, writeLastPath } from './topbarPrefs'
import { INSTANCE_NAME_PATTERN } from './instanceName'

/* 旧版外壳下也要显示居中页名的顶层路由。 */
const PRIMARY_NAV_PATHS = ['/announcement', '/updater', '/interface', '/remote', '/configs', '/settings', '/dev']
const SETUP_PATH = '/setup'

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
    <label>{ui('instance.name')}<input autoFocus required pattern={INSTANCE_NAME_PATTERN} value={name} onChange={event => setName(event.target.value)} placeholder={ui('instance.namePlaceholder')} maxLength={64}/></label>
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

export function App() {
  const connection = useConnection()
  const {instancesLoaded, instances, schema, t, ui, notify, previewEnabled, devMode, setDevMode, theme, compactRailSide} = useApp()
  /* 开发者工具的模拟状态：只影响实例状态徽章与更新角标。 */
  const devOverride = useDevOverride()
  const {instance} = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const [creating, setCreating] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [railOpen, setRailOpen] = useState(false)
  /* 只区分「全新打开」与「刷新 / 后退前进」：前者才回上次选中的实例。
     刷新时地址栏已经是用户要停留的页面，写进去就不再改。 */
  const freshOpen = useRef((performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined)?.type === 'navigate')
  const update = useUpdater()
  const announcement = useAnnouncement()
  usePageMotion()
  useGlassPointerLight()
  useSystemNotifications()
  const current = instances.find(item => item.name === instance)
  const subscribedInstance = current?.name ?? null
  const base = instance ? `/i/${encodeURIComponent(instance)}` : ''
  const taskMatch = location.pathname.match(/\/task\/([^/]+)/)
  const currentTask = taskMatch ? taskMatch[1] : null
  /* 图形调度是系统编辑页，不伪装成可执行的游戏任务。 */
  const schedulerEditor = currentTask === SCHEDULER_EDITOR
  const stockExchange = location.pathname.endsWith('/stock-exchange')
  const currentTaskLabel = currentTask ? taskLabel(currentTask, ui, t) : ''
  const activeSection = location.pathname === '/announcement' ? ui('nav.announcement') : location.pathname === '/settings' ? ui('nav.settings') : location.pathname === '/interface' ? ui('nav.interface') : location.pathname === '/remote' ? ui('nav.remote') : location.pathname === '/updater' ? ui('nav.updater') : location.pathname === '/configs' ? ui('nav.configs') : location.pathname === '/dev' ? ui('nav.developer') : ''
  const entryPath = instances.length > 0 ? `/i/${encodeURIComponent(instances[0].name)}/overview` : '/configs'
  const setup = location.pathname === SETUP_PATH
  const empty = instancesLoaded && instances.length === 0
  function handleBrandLogoClick(event: MouseEvent<HTMLImageElement>) {
    if (devMode || !recordDevLogoClick()) return
    event.preventDefault()
    setDevMode(true)
    notify(ui('developer.enabled'))
    navigate('/dev')
  }
  useEffect(() => {
    if (connection !== 'ready') return
    if (empty) {
      if (!setup) navigate(SETUP_PATH, {replace: true})
    } else if ((setup && instancesLoaded) || (instancesLoaded && instance && !current)) {
      navigate(entryPath, {replace: true})
    }
  }, [connection, current, empty, entryPath, instance, instancesLoaded, navigate, setup])
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
  /* 点导航里当前页的链接不产生 pathname 变化，抽屉得自己关。 */
  const closeDrawer = () => setMobileOpen(false)
  useEffect(() => { setMobileOpen(false); setRailOpen(false) }, [location.pathname])
  useEffect(() => {
    if (connection !== 'ready') return
    const topics: Array<'notifications' | 'instances' | 'launcher' | 'stock' | 'overview' | 'logs' | 'preview'> = ['notifications', 'instances']
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
  const legacyGlobalShell = PRIMARY_NAV_PATHS.includes(location.pathname) && usesLegacyLayout(theme)
  const legacyShell = usesLegacyShell(theme, instance) || legacyGlobalShell
  // 旧版把调度器与任务计划放进实例页左列，右栏整体让位，否则同一块内容会出现两处。
  const showRail = showsRightRail(theme, instance) && !schedulerEditor && currentTask !== FLEET_ANALYSIS && currentTask !== FLEET_SWITCH && currentTask !== FLEET_TRAINING && currentTask !== FLEET_LEVEL_TRAINING && currentTask !== FLEET_AFFINITY_TRAINING && currentTask !== FLEET_EQUIPMENT && currentTask !== FLEET_ROTATION && !stockExchange && !location.pathname.endsWith('/resources') && !location.pathname.endsWith('/task/FleetInfo') && !(location.pathname.endsWith('/statistics') && new URLSearchParams(location.search).get('view') === 'management')
  /* 紧凑主题可把调度与任务计划栏换到内容区左侧。换位走 DOM 顺序而不是 CSS order，
     键盘 Tab 的顺序才会跟看到的顺序一致；列宽与顶栏跨栏方向由 compact.css 按同一偏好调整。 */
  const railFirst = theme === 'extreme' && compactRailSide === 'left'
  /* 新版玻璃主题里，顶栏与右栏同装一个容器（.shell-frame）：一级层由容器画一次，
     两块之间不再各自算一次毛玻璃。其余家族不导入那份样式，容器不参与布局，右栏仍留在外壳层。 */
  const railInFrame = Boolean(instance) && showRail && usesMaterial(theme) && !railFirst
  const rail = <RightRail instance={instance!} onMobileClose={() => setRailOpen(false)}/>
  // 开发者工具可以预览「有可用更新」的角标，这里统一算一次。
  const updateAvailable = Boolean(update.data?.available) || devOverride.updatePreview
  const brand = <><Link to="/settings" className="brand-title" aria-label={`AzurPilot ${ui('nav.settings')}`} onClick={closeDrawer}><ProjectLogo className="brand-logo" onClick={handleBrandLogoClick}/><span>AzurPilot</span></Link>{updateAvailable && <Link className="update-notice sidebar-update-notice" to="/updater" aria-label={ui('nav.newVersion')} title={ui('nav.newVersion')}><span>{ui('nav.newBadge')}</span></Link>}</>
  // 旧版顶栏的第三列是居中的页面名：实例页写任务名，无实例时写导航项名。
  const pageTitle = instance
    ? currentTask ? currentTaskLabel : location.pathname.endsWith('/resources') ? ui('nav.resources') : location.pathname.endsWith('/statistics') ? ui('nav.statistics') : ui('nav.overview')
    : activeSection
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
    <InstanceTabs onCreate={() => setCreating(true)}/>
  </>
  const topbar = <header className="topbar">
    {legacyShell && <div className="sidebar-brand legacy-topbar-brand"><div className="sidebar-brand-left">{brand}</div></div>}
    <GlassMaterial/><button className="mobile-toggle icon-button" aria-label={ui('nav.open')} onClick={() => setMobileOpen(true)}><Menu size={20}/></button>{showRail && <button className="mobile-rail-toggle icon-button" aria-label={railOpen ? ui('nav.closeRail') : ui('nav.openRail')} aria-expanded={railOpen} aria-controls="right-rail-menu" title={railOpen ? ui('nav.closeRail') : ui('nav.openRail')} onClick={() => setRailOpen(open => !open)}><CalendarClock size={18}/></button>}
    {legacyShell
      ? <span className="legacy-topbar-title">{pageTitle}</span>
      : <div className="breadcrumb with-tabs">{tabNav}{currentTask
        ? <Link className="breadcrumb-current" to={`${base}/task/${currentTask}`}><strong>{currentTaskLabel}</strong></Link>
        : activeSection && <strong className="breadcrumb-current">{activeSection}</strong>}</div>}
    {!legacyShell && <TabBarResizeHandle label={ui('nav.tabSize')}/>}
  </header>
  // 旧版在居中页名下方显示实例标签与任务切换器。
  const pageNav = <div className="legacy-page-nav">
    <div className="breadcrumb with-tabs">{tabNav}{currentTask && <TaskSwitcher/>}</div>
    <TabBarResizeHandle label={ui('nav.tabSize')}/>
  </div>
  /* shell 自己必须订阅：收起状态变了要重渲染才能加上 nav-collapsed 类（按钮订阅管不到这里）。 */
  const layout = useSyncExternalStore(subscribeLayout, getLayout, getLayout)
  /* 检视器停靠时整块画布要为它让出宽度，所以外壳自己订阅，靠类名驱动。 */
  const inspector = useSyncExternalStore(subscribeMaterialInspector, getMaterialInspector, getMaterialInspector)
  /* 登录页要在所有 Hook 调用之后返回：否则同一次会话里的 Hook 数量会随连接状态变化，
     隧道远程访问首帧就走 auth，React 会直接抛 #300 崩掉整页。 */
  if (connection === 'auth') return <Login/>
  if (setup || empty) return <main className="instance-setup">{setup && empty && schema ? <Outlet/> : <Loading/>}</main>
  const hasDockedInspector = inspector.open && inspector.docked && !inspector.minimized
  return <div
    className={`app-shell ${layout.sidebarCollapsed ? 'nav-collapsed' : ''} ${hasDockedInspector ? 'has-docked-inspector' : ''} ${showRail ? 'with-rail' : ''} ${currentTask ? 'task-config-shell' : ''} ${legacyShell ? 'legacy-shell' : ''} ${legacyGlobalShell ? 'legacy-global-shell' : ''} ${mobileOpen ? 'mobile-open' : ''} ${railOpen ? 'rail-open' : ''}`}
    style={layout.sidebarWidth != null ? ({'--sidebar-width': `${layout.sidebarWidth}px`} as React.CSSProperties) : undefined}
  >
    <a className="skip-link" href="#main-content" onClick={event => {event.preventDefault(); document.getElementById('main-content')?.focus()}}>{ui('nav.skipContent')}</a>
    {legacyShell && topbar}
    <NavHandle/>
    <aside className="sidebar">
      <SidebarResizeHandle label="拖动调整侧边栏宽度（双击恢复默认）"/>
      {/* 旧版把招牌放进顶栏，桌面端这一行隐藏；窄屏侧栏是抽屉，招牌回抽屉里。 */}
      <div className={`sidebar-brand ${legacyShell ? 'legacy-sidebar-actions' : ''}`.trim()}><div className="sidebar-brand-left">{brand}</div><button className="mobile-close icon-button" aria-label={ui('nav.close')} onClick={() => setMobileOpen(false)}><X size={18}/></button></div>
      <SidebarTransition viewKey={instance ? `instance:${instance}` : 'global'}>
        <nav className="primary-nav" aria-label={ui('nav.primary')}>
          {instance ? <><NavLink to={`${base}/overview`} onClick={closeDrawer}><LayoutDashboard size={17}/>{ui('nav.overview')}</NavLink><NavLink to={`${base}/statistics`} onClick={closeDrawer}><ChartNoAxesCombined size={17}/>{ui('nav.statistics')}</NavLink><NavLink to={`${base}/stock-exchange`} onClick={closeDrawer}><Cat size={17}/>{ui('stock.name')}</NavLink></> : <><NavLink to="/announcement" onClick={closeDrawer}><Megaphone size={17}/>{ui('nav.announcement')}{announcement.unread && <span className="tiny-dot red"/>}</NavLink><NavLink to="/updater" onClick={closeDrawer}><Download size={17}/>{ui('nav.updater')}{updateAvailable && <span className="tiny-dot teal"/>}</NavLink><NavLink to="/interface" onClick={closeDrawer}><Palette size={17}/>{ui('nav.interface')}</NavLink><NavLink to="/remote" onClick={closeDrawer}><Globe size={17}/>{ui('nav.remote')}</NavLink><NavLink to="/configs" onClick={closeDrawer}><FileJson size={17}/>{ui('nav.configs')}</NavLink><NavLink to="/settings" onClick={closeDrawer}><Settings2 size={17}/>{ui('nav.settings')}</NavLink><NavLink to="/dev" onClick={closeDrawer}><Code2 size={17}/>{ui('nav.developer')}</NavLink><a className="nav-open-source" href="https://github.com/wess09/AzurPilot" target="_blank" rel="noreferrer" onClick={closeDrawer}><ExternalLink size={17}/>{ui('nav.openSource')}</a></>}
        </nav>
        {instance && <TaskNav onNavigate={closeDrawer}/>}
      </SidebarTransition>
    </aside>
    {railFirst && instance && showRail && rail}
    <div className="main-shell">
      <div className="shell-frame">{!legacyShell && topbar}{railInFrame && rail}</div>
      {legacyShell && pageNav}
      {connection !== 'ready' && <div className="connection-banner" role="status"><WifiOff size={16}/>{ui('connection.connecting')}</div>}
      <main id="main-content" tabIndex={-1}>{!schema || location.pathname === '/' || (instance && (!instancesLoaded || !current)) ? <Loading/> : <Outlet context={update} key={instance ?? 'global'}/>}</main>
    </div>
    {!railFirst && instance && showRail && !railInFrame && rail}
    <CompactScrollbars/>
    {creating && <CreateInstance onClose={() => setCreating(false)}/>}
    <MaterialInspector/>
  </div>
}
