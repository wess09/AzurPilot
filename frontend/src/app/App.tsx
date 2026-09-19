import { PasswordInput, Select } from '../components/FormControls'
import { useEffect, useState, type FormEvent, type MouseEvent } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'
import { ArrowRight, CalendarClock, ChartNoAxesCombined, Code2, Compass, LayoutDashboard, Globe, House, Download, Menu, Palette, Settings2, WifiOff, X } from 'lucide-react'
import { api } from '../api/client'
import { useApp, useConnection } from './context'
import { ErrorBox, Loading, Modal } from '../components/ui'
import { GlassMaterial } from '../components/GlassMaterial'
import { InstanceSwitcher } from '../components/InstanceSwitcher'
import { RightRail } from '../components/RightRail'
import { TaskNav } from '../components/TaskNav'
import { TaskSwitcher } from '../components/TaskSwitcher'
import { useUpdater } from './updater'
import { recordDevLogoClick } from './devMode'
import { usesLegacyShell, showsRightRail } from './theme'
import { INSTANCE_NAME_PATTERN } from './instanceName'

export function CreateInstance({onClose}: {onClose: () => void}) {
  const [name, setName] = useState('')
  const [source, setSource] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const {instances, refresh, notify, ui} = useApp()
  const navigate = useNavigate()
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      await api.request('instances.create', {name, source: source || null})
      await refresh(); onClose(); notify(ui('instance.created'))
      navigate(`/i/${name}/task/Alas`)
    } catch (error) { setError((error as Error).message) } finally { setBusy(false) }
  }
  return <Modal title={ui('instance.createTitle')} onClose={onClose}><form onSubmit={submit} className="form-stack">
    <p className="muted">{ui('instance.createHint')}</p>
    <label>{ui('instance.name')}<input autoFocus required pattern={INSTANCE_NAME_PATTERN} value={name} onChange={event => setName(event.target.value)} placeholder={ui('instance.namePlaceholder')} maxLength={64}/></label>
    <label>{ui('instance.initialConfig')}<Select value={source} onChange={event => setSource(event.target.value)}><option value="">{ui('instance.defaultConfig')}</option>{instances.map(item => <option key={item.name}>{item.name}</option>)}</Select></label>
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
  return <div className="login-page"><div className="login-art"><Compass size={200} strokeWidth={0.5}/><span>{ui('auth.slogan')}</span></div>
    <form onSubmit={submit} className="login-card"><div className="brand-mark"><NavigationMark/></div><h1>{ui('auth.welcome')}</h1>
      <label htmlFor="password">{ui('auth.password')}</label><PasswordInput id="password" autoComplete="current-password" autoFocus required value={password} onChange={event => setPassword(event.target.value)}/>
      {error && <ErrorBox message={error}/>}
      <button className="button primary" disabled={busy}>{busy ? ui('auth.verifying') : ui('auth.enter')}<ArrowRight size={16}/></button>
      <small>{ui('auth.passwordHint')}</small>
    </form></div>
}

export function NavigationMark() {
  return <img src={`${import.meta.env.BASE_URL}azurpilot.svg`} alt="AzurPilot" width="28" height="28" className="brand-logo"/>
}

export function App() {
  const connection = useConnection()
  const {instancesLoaded, instances, schema, t, ui, notify, previewEnabled, devMode, setDevMode, theme} = useApp()
  const {instance} = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const [creating, setCreating] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [railOpen, setRailOpen] = useState(false)
  const update = useUpdater()
  const current = instances.find(item => item.name === instance)
  const base = instance ? `/i/${instance}` : ''
  const taskMatch = location.pathname.match(/\/task\/([^/]+)/)
  const currentTask = taskMatch ? taskMatch[1] : null
  const activeSection = location.pathname.includes('/task/') ? ui('nav.taskConfig') : location.pathname.endsWith('/statistics') ? ui('nav.statistics') : location.pathname.endsWith('/settings') ? ui('nav.settings') : location.pathname.endsWith('/interface') ? ui('nav.interface') : location.pathname.endsWith('/remote') ? ui('nav.remote') : location.pathname.endsWith('/updater') ? ui('nav.updater') : location.pathname.endsWith('/dev') ? ui('nav.developer') : instance ? instance : ui('nav.home')
  function handleBrandLogoClick(event: MouseEvent<HTMLImageElement>) {
    if (devMode || !recordDevLogoClick()) return
    event.preventDefault()
    setDevMode(true)
    notify(ui('developer.enabled'))
    navigate('/dev')
  }
  useEffect(() => {
    if (connection === 'ready' && instancesLoaded && instance && !instances.some(item => item.name === instance)) {
      navigate('/', {replace: true})
    }
  }, [connection, instances, instance, navigate, instancesLoaded])
  useEffect(() => { setMobileOpen(false); setRailOpen(false) }, [location.pathname])
  useEffect(() => {
    if (connection !== 'ready') return
    void api.request('events.subscribe', {instance: instance ?? null, topics: instance ? previewEnabled ? ['instances', 'overview', 'logs', 'preview'] : ['instances', 'overview', 'logs'] : ['instances']}).catch(error => notify(error.message, true))
  }, [instance, connection, notify, previewEnabled])
  if (connection === 'auth') return <Login/>
  // 旧版主题下点进实例后，外壳回到「顶栏跨全宽 + 单列侧栏」；主页视图一律沿用新版外壳。
  const legacyShell = usesLegacyShell(theme, instance)
  // 旧版把调度器与任务计划放进实例页左列，右栏整体让位，否则同一块内容会出现两处。
  const showRail = showsRightRail(theme, instance)
  const brand = <><Link to="/" className="brand-title" aria-label={`AzurPilot ${ui('nav.home')}`}><img src={`${import.meta.env.BASE_URL}azurpilot.svg`} alt="" className="brand-logo" onClick={handleBrandLogoClick}/><span>AzurPilot</span></Link>{update.data?.available && <Link className="update-notice sidebar-update-notice" to="/updater" aria-label={ui('nav.newVersion')} title={ui('nav.newVersion')}><span>{ui('nav.newBadge')}</span></Link>}</>
  // 旧版顶栏的第三列是居中的页面名，面包屑里的页名会被它取代。
  const pageTitle = instance
    ? currentTask ? t(`Task.${currentTask}.name`) : location.pathname.endsWith('/statistics') ? ui('nav.statistics') : ui('nav.overview')
    : ''
  const topbar = <header className="topbar">
    {legacyShell && <div className="sidebar-brand legacy-topbar-brand"><div className="sidebar-brand-left">{brand}</div></div>}
    <GlassMaterial/><button className="mobile-toggle icon-button" aria-label={ui('nav.open')} onClick={() => setMobileOpen(true)}><Menu size={20}/></button>{showRail && <button className="mobile-rail-toggle icon-button" aria-label={railOpen ? ui('nav.closeRail') : ui('nav.openRail')} aria-expanded={railOpen} aria-controls="right-rail-menu" title={railOpen ? ui('nav.closeRail') : ui('nav.openRail')} onClick={() => setRailOpen(open => !open)}><CalendarClock size={18}/></button>}
    {legacyShell
      ? <span className="legacy-topbar-title">{pageTitle}</span>
      : <div className="breadcrumb"><Link to="/">{ui('nav.home')}</Link>{instance ? <><span>/</span><InstanceSwitcher onCreate={() => setCreating(true)}/>{currentTask ? <><span>/</span><Link to={`${base}/task/Alas`}>{ui('nav.taskConfig')}</Link><span>/</span><Link className="breadcrumb-current" to={`${base}/task/${currentTask}`}><strong>{t(`Task.${currentTask}.name`)}</strong></Link></> : location.pathname.endsWith('/statistics') && <><span>/</span><strong>{ui('nav.statistics')}</strong></>}</> : activeSection !== ui('nav.home') && <><span>/</span><strong>{activeSection}</strong></>}</div>}
  </header>
  // 旧版顶栏只留招牌与居中的页面名，「主页 / 实例 / 任务」这一行落到内容区顶部。
  const pageNav = <div className="legacy-page-nav"><div className="breadcrumb"><Link to="/">{ui('nav.home')}</Link><span>/</span><InstanceSwitcher onCreate={() => setCreating(true)}/>{currentTask && <><span>/</span><TaskSwitcher/></>}</div></div>
  return <div className={`app-shell ${showRail ? 'with-rail' : ''} ${legacyShell ? 'legacy-shell' : ''} ${mobileOpen ? 'mobile-open' : ''} ${railOpen ? 'rail-open' : ''}`}>
    <a className="skip-link" href="#main-content" onClick={event => {event.preventDefault(); document.getElementById('main-content')?.focus()}}>{ui('nav.skipContent')}</a>
    {legacyShell && topbar}
    <aside className="sidebar">
      {/* 旧版把招牌放进顶栏，桌面端这一行隐藏；窄屏侧栏是抽屉，招牌回抽屉里。 */}
      <div className={`sidebar-brand ${legacyShell ? 'legacy-sidebar-actions' : ''}`.trim()}><div className="sidebar-brand-left">{brand}</div><button className="mobile-close icon-button" aria-label={ui('nav.close')} onClick={() => setMobileOpen(false)}><X size={18}/></button></div>
      <nav className="primary-nav" aria-label={ui('nav.primary')}>
        {instance ? <><NavLink to={`${base}/overview`}><LayoutDashboard size={17}/>{ui('nav.overview')}</NavLink><NavLink to={`${base}/statistics`}><ChartNoAxesCombined size={17}/>{ui('nav.statistics')}</NavLink></> : <><NavLink to="/" end><House size={17}/>{ui('nav.home')}</NavLink><NavLink to="/updater"><Download size={17}/>{ui('nav.updater')}{update.data?.available && <span className="tiny-dot teal"/>}</NavLink><NavLink to="/interface"><Palette size={17}/>{ui('nav.interface')}</NavLink><NavLink to="/remote"><Globe size={17}/>{ui('nav.remote')}</NavLink><NavLink to="/settings"><Settings2 size={17}/>{ui('nav.settings')}</NavLink>{devMode && <NavLink to="/dev"><Code2 size={17}/>{ui('nav.developer')}</NavLink>}</>}
      </nav>
      {instance && <TaskNav/>}
    </aside>
    <div className="main-shell">{!legacyShell && topbar}
      {legacyShell && pageNav}
      {connection !== 'ready' && <div className="connection-banner" role="status"><WifiOff size={16}/>{ui('connection.connecting')}</div>}
      <main id="main-content" tabIndex={-1}>{!schema || ((instance || location.pathname === '/') && !instancesLoaded) ? <Loading/> : !instance || current ? <Outlet context={update} key={instance ?? 'home'}/> : <Loading/>}</main>
    </div>
    {instance && showRail && <RightRail instance={instance} onMobileClose={() => setRailOpen(false)}/>}
    {creating && <CreateInstance onClose={() => setCreating(false)}/>}
  </div>
}
