/**
 * @fileoverview 任务参数设置页面。
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'
import type { CSSProperties } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ListTree, PanelLeft, PanelRight, Play, RotateCcw, Search, Settings2, Terminal, X } from 'lucide-react'
import { api } from '../api/client'
import type { Config } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { usePageRead } from '../app/usePageRead'
import { htmlToPlainText } from '../app/htmlText'
import { getLayout, subscribeLayout } from '../app/layout'
import { readRailVisible, subscribeRailVisible } from '../app/railPrefs'
import { readSchedulerPosition, subscribeSchedulerPosition } from '../app/schedulerPositionPrefs'
import { smoothScrollToElement } from '../app/scroll'
import { clearSearchTarget, peekSearchTarget, subscribeSearchTarget } from '../app/searchTarget'
import { Empty, ErrorBox, Modal, PageTitle, Panel, PanelHeading } from '../components/ui'
import { LoadBoundary } from '../components/ui/load-boundary'
import { Input } from '../components/ui/input'
import { LogPanel } from '../components/LogPanel'
import { MeowfficerScorePanel } from '../components/MeowfficerScorePanel'
import { OpsiSimulatorPanel } from '../components/OpsiSimulatorPanel'
import { FieldInput } from '../components/FieldInput'
import { StorageField } from '../components/StorageField'
import { ModernRail } from '../components/ModernRail'
import { ModernRailResizeHandle } from '../components/ModernRailResizeHandle'
import { useInstanceOverview } from '../components/useInstanceOverview'
import { editor, prepareValue } from '../config/editors'
import { EditStatus } from '../components/EditStatus'
import { AccountPanel } from '../components/AccountPanel'
import { isFieldVisible } from './configVisibility'
import { FleetInfoPage } from './FleetInfoPage'

/** Match viewport rules, including the mobile stacked layout. */
function useFoldFlag(query: string): boolean {
  const subscribe = useCallback((listener: () => void) => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return () => {}
    const media = window.matchMedia(query)
    media.addEventListener('change', listener)
    return () => media.removeEventListener('change', listener)
  }, [query])
  const getSnapshot = useCallback(() => (
    typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(query).matches
  ), [query])
  return useSyncExternalStore(subscribe, getSnapshot, () => false)
}

/** 任务参数设置页：参数卡就地编辑、侧栏搜索定位、任务级说明与启动开关；工具任务页改为挂日志面板。 */
export function TaskConfig() {
  const {instance = '', task = ''} = useParams()
  const {schema, t, ui, notify} = useApp()
  const connection = useConnection()
  const railVisibility = useSyncExternalStore(subscribeRailVisible, readRailVisible, readRailVisible)
  const schedulerPosition = useSyncExternalStore(subscribeSchedulerPosition, readSchedulerPosition, readSchedulerPosition)
  // 调度器列的宽度与总览页共用同一个持久化值，拖动任一处另一边跟着变。
  const layout = useSyncExternalStore(subscribeLayout, getLayout, getLayout)
  // Measure the grid itself: saved or dragged sidebar widths change the space
  // available without changing the viewport. Thresholds match the old desktop
  // breakpoints after subtracting the default sidebar and main padding.
  const [gridNode, setGridNode] = useState<HTMLDivElement | null>(null)
  const [gridWidth, setGridWidth] = useState<number | null>(null)
  useEffect(() => {
    if (!gridNode || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => { if (entry) setGridWidth(entry.contentRect.width) })
    observer.observe(gridNode)
    return () => observer.disconnect()
  }, [gridNode])
  const desktop = useFoldFlag('(min-width: 951px)')
  const directoryViewportFolded = useFoldFlag('(min-width: 951px) and (max-width: 1319px)')
  const railViewportFolded = useFoldFlag('(min-width: 951px) and (max-width: 1089px)')
  const directoryFolded = directoryViewportFolded || (desktop && gridWidth !== null && gridWidth < 1024)
  const railFolded = railViewportFolded || (desktop && gridWidth !== null && gridWidth < 794)
  // 抽屉一次只开一个；窗口跨回宽档或用户手动隐藏调度器栏时自动收回。
  const [popout, setPopout] = useState<'directory' | 'rail' | null>(null)
  const directoryRef = useRef<HTMLElement>(null)
  const railRef = useRef<HTMLDivElement>(null)
  const openerRef = useRef<HTMLButtonElement | null>(null)
  useEffect(() => {
    if (popout === 'directory' && !directoryFolded) setPopout(null)
    if (popout === 'rail' && (!railFolded || railVisibility !== 'shown')) setPopout(null)
  }, [popout, directoryFolded, railFolded, railVisibility])
  useLayoutEffect(() => {
    if (!popout) return
    const drawer = popout === 'directory' ? directoryRef.current : railRef.current
    if (!drawer) return
    const opener = openerRef.current
    const focusable = () => Array.from(drawer.querySelectorAll<HTMLElement>(
      'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
    )).filter(element => element.getClientRects().length > 0 && element.tabIndex >= 0)
    // The scheduler can open a portalled confirmation dialog or context menu.
    // Let that surface manage focus and Escape until it closes.
    const hasPortalledSurface = () => Array.from(document.querySelectorAll('[role="dialog"][data-state="open"], .context-menu[role="menu"]'))
      .some(element => !drawer.contains(element))
    const focusFirst = () => (focusable()[0] ?? drawer).focus()
    focusFirst()
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || hasPortalledSurface() || (event.target instanceof Element && !drawer.contains(event.target) && event.target.closest('[role="dialog"], [role="menu"]'))) return
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        setPopout(null)
      } else if (event.key === 'Tab') {
        const items = focusable()
        const index = items.indexOf(document.activeElement as HTMLElement)
        if (!items.length || index < 0 || (event.shiftKey && index === 0) || (!event.shiftKey && index === items.length - 1)) {
          event.preventDefault()
          ;((event.shiftKey ? items[items.length - 1] : items[0]) ?? drawer).focus()
        }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      if (opener?.isConnected && opener.getClientRects().length) opener.focus()
    }
  }, [popout])
  // 右列现在同时承载目录与调度器，进页面就要拉一份总览数据。
  const [railData, setRailData] = useInstanceOverview(instance, true)
  // Task navigation revalidates the instance snapshot through usePageRead's loader lifecycle.
  const loadConfig = useCallback(() => api.request('config.get', {instance}), [instance, task])
  const {data: config, error: configError, reload, setData: setConfig} = usePageRead(instance, connection === 'ready' && task !== 'FleetInfo', loadConfig)
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmRun, setConfirmRun] = useState(false)

  const queue = editor(`config:${instance}`)
  const {edits, storageError} = useSyncExternalStore(queue.subscribe, queue.getSnapshot, queue.getSnapshot)
  const startupQueue = editor(`startup:${instance}`)
  const startupEdits = useSyncExternalStore(startupQueue.subscribe, startupQueue.getSnapshot, startupQueue.getSnapshot)
  const loadStartup = useCallback(() => api.request('startup.get', {instance}), [instance])
  const {data: startup, error: startupError, reload: reloadStartup, setData: setStartup} = usePageRead(instance, connection === 'ready' && task === 'Alas', loadStartup)
  const {enabled: startupEnabled, remember: startupRemember} = startup ?? {}

  // Publish the save response through the read controller to invalidate older reads.
  useEffect(() => {
    queue.onSaved = data => setConfig(data as Config)
    return () => {queue.onSaved = undefined}
  }, [queue, setConfig])
  useEffect(() => {
    startupQueue.onSaved = data => setStartup(data as NonNullable<typeof startup>)
    return () => {startupQueue.onSaved = undefined}
  }, [startupQueue, setStartup])

  async function run() {
    setBusy(true); setError('')
    try {
      await queue.settled()
      await api.request('tasks.run', {instance, task})
      notify(ui('task.started'))
    } catch (error) {
      setError((error as Error).message)
    } finally {
      setBusy(false)
      setConfirmRun(false)
    }
  }

  const groups = schema?.args[task]
  const visibleGroups = Object.entries(groups ?? {}).map(([group, fields]) => {
    const visible = Object.entries(fields).filter(([arg, field]) => {
      const edit = edits[`${task}.${group}.${arg}`]
      const value = edit?.status === 'saved' ? edit.value : config?.values[task]?.[group]?.[arg] ?? field.value
      return isFieldVisible(arg, field, value) && `${t(`${group}.${arg}.name`)} ${group}.${arg}`.toLowerCase().includes(search.toLowerCase())
    })
    return {group, visible}
  }).filter(({visible}) => visible.length)

  const tool = Object.values(schema?.menu ?? {}).some(group => group.page === 'tool' && group.tasks.includes(task))
  // 指挥喵评分保留参数卡（评分来源、截图目录等），报告面板挂在参数卡上方。
  const scorePanel = task === 'MeowfficerScore' ? <MeowfficerScorePanel instance={instance}/> : null
  const showConfigToolbar = task !== 'FleetInfo' && Boolean(groups) && (visibleGroups.length > 0 || Boolean(search))

  // 侧栏搜索点进来的定位：字段要等配置加载、分组渲染完才存在，所以轮询等它出现。
  // 挂载时查一次，覆盖从别的任务跳过来的情形；订阅覆盖命中项就在本页的情形，那时路由没变。
  useEffect(() => {
    let find: number | undefined

    const locate = () => {
      const path = peekSearchTarget()
      if (!path || !path.startsWith(`${task}.`)) return
      if (find) window.clearInterval(find)
      let attempts = 0
      // 卡片命中给两段路径（任务.分组），配置项命中给三段；据此选 DOM id 与滚动方式。
      const segments = path.split('.')
      const isCard = segments.length <= 2
      const elementId = isCard ? `group-${segments[1]}` : path
      find = window.setInterval(() => {
        const field = document.getElementById(elementId)
        attempts += 1
        if (field) {
          window.clearInterval(find)
          find = undefined
          clearSearchTarget()
          const row = field.closest('.field-row') ?? field
          row.scrollIntoView({block: isCard ? 'start' : 'center'})
          row.classList.add('is-search-target')
          window.setTimeout(() => row.classList.remove('is-search-target'), 3000)
        } else if (attempts > 20) {
          // 等不到字段（被隐藏或该任务下没有这一项）就放弃，不再重试。
          window.clearInterval(find)
          find = undefined
          clearSearchTarget()
        }
      }, 150)
    }

    locate()
    const unsubscribe = subscribeSearchTarget(locate)
    return () => {
      unsubscribe()
      if (find) window.clearInterval(find)
    }
  }, [config, task])

  if (task === 'FleetInfo') return <FleetInfoPage key={instance}/>
  if (!config) return <LoadBoundary ready={false} error={configError} retry={reload}/>

  const modal = confirmRun && (
    <Modal title={ui('task.runTitle', {task: t(`Task.${task}.name`)})} onClose={() => setConfirmRun(false)}>
      <p>{ui('task.runWarning')}</p>
      <button className="button primary" disabled={busy} onClick={run}>
        <Play size={15} />{ui('task.confirmRun')}
      </button>
    </Modal>
  )

  const groupCards = <>{visibleGroups.map(({group, visible}) => (
    <Panel compact key={group} id={'group-' + group}>
      <PanelHeading title={t(group + '._info.name')} icon={<span className="group-indicator"/>}/>
      {visible.map(([arg, definition]) => {
        const path = `${task}.${group}.${arg}`
        const field = {...definition, option: config.options?.[path] ?? definition.option}
        const edit = edits[path]
        const value = edit ? edit.value : config.values[task]?.[group]?.[arg] ?? field.value
        const label = t(`${group}.${arg}.name`)
        const help = t(`${group}.${arg}.help`)
        const readonly = ['disabled', 'readonly'].includes(field.display ?? '') || ['storage', 'stored', 'state', 'lock'].includes(field.type)
        // 「立刻运行」只对每个任务的调度时间有意义，其他时间字段（如仪表盘记录时间）不显示。
        const runNow = group === 'Scheduler' && arg === 'NextRun' && !readonly
        const clearProgress = path === 'OpsiExplore.OpsiExplore.ExploreProgress'
          || path === 'OpsiScheduling.OpsiSmartExplore.Progress'
        const isMultiline = ['textarea', 'task_priority', 'yaml', 'storage'].includes(field.type) || field.mode === 'yaml'

        return (
          <div className={`field-row ${isMultiline ? 'field-row-multiline' : ''}`} key={arg}>
            <div className="field-label">
              <label htmlFor={path}>
                {label}
                {readonly && <span className="small-label">{ui('task.readonly')}</span>}
              </label>
              {help && help !== 'help' && help !== arg && <p>{htmlToPlainText(help)}</p>}
              {/* 优先级调整直接跳到图形调度编辑器：它才是真正编排顺序的地方。 */}
              {task === 'General' && group === 'YukikazeTaskManager' && arg === 'TaskPriorityAdjustment' && <Link className="button secondary" to={`/i/${instance}/task/SchedulerProgram`}>{ui('nav.schedulerProgram')}</Link>}
              {/* 多行控件的提示跟标题同一行，浮在它右端。 */}
              {isMultiline && <EditStatus id={path} edit={edit} />}
            </div>
            <div className="field-control">
              {field.type === 'storage' ? (
                <StorageField value={value} disabled={false} onClear={() => queue.change(path, {})} />
              ) : (
                <FieldInput
                  id={path}
                  value={value}
                  mode={field.mode}
                  type={field.type === 'input' && typeof field.value === 'number' ? 'number' : field.type}
                  options={field.option}
                  disabled={readonly}
                  preserveText
                  // 实测心情重新输入同一值也要提交，建立新的校准时刻。
                  resubmitOnEdit={(group === 'Emotion' && /^Fleet[12]Value$/.test(arg)) || (group === 'PublicEmotion' && arg === 'FleetValue')}
                  invalid={edit?.status === 'error'}
                  label={label}
                  translateOption={option => t(`${group}.${arg}.${option}`)}
                  onChange={next => {
                    const {payload, text, error} = prepareValue(next, field)
                    queue.change(path, text ?? next, payload, error)
                  }}
                />
              )}
              {runNow && (
                <div className="field-actions">
                  <button type="button" className="button subtle icon-only" aria-label={ui('task.runNow')} title={ui('task.runNow')} disabled={connection !== 'ready'}
                    onClick={() => {
                      // 按钮等同清空该字段：空时间按参数默认值提交，调度器下一轮即把任务视为待运行。
                      const {payload, text, error} = prepareValue('', field)
                      queue.change(path, text ?? '', payload, error)
                    }}><Play size={15}/></button>
                </div>
              )}
              {clearProgress && (
                <div className="field-actions">
                  <button type="button" className="button subtle icon-only" aria-label={ui('task.clearExploreProgress')}
                    title={ui('task.clearExploreProgressHelp')} disabled={connection !== 'ready' || edit?.status === 'saving'}
                    onClick={() => queue.change(path, '')}><RotateCcw size={15}/></button>
                </div>
              )}
              {!isMultiline && <EditStatus id={path} edit={edit} />}
            </div>
          </div>
        )
      })}
    </Panel>
  ))}
  {search && !visibleGroups.length && <Empty icon={<Search size={26} />} title={ui('task.noConfigFound')}>{ui('task.tryOtherKeyword')}</Empty>}
  </>

  const hasGroups = task !== 'FleetInfo' && Boolean(groups) && visibleGroups.length > 0
  // 只有紧凑主题把搜索框并进左列（跳转栏下方），其余主题保持标题下方的原样。
  // 启动开关挂在系统设置（Alas）任务页顶部；搜索时只显示匹配项。
  const startupPanel = task === 'Alas' && !search && <Panel compact>
    <PanelHeading title={ui('instance.startup')} icon={<span className="group-indicator"/>}/>
    <div className="field-row">
      <div className="field-label">
        <span className="field-name">{ui('instance.autoRun')}</span>
        <p>{ui('instance.autoRunHelp')}</p>
      </div>
      <div className="field-control">
        <FieldInput id="instance-startup" label={ui('instance.autoRun')} value={startupEdits.edits.enabled?.value ?? startupEnabled ?? false} disabled={startupEnabled === undefined} onChange={value => startupQueue.change('enabled', value)}/>
        <EditStatus id="instance-startup" edit={startupEdits.edits.enabled}/>
      </div>
    </div>
    <div className="field-row">
      <div className="field-label">
        <span className="field-name">{ui('instance.rememberRun')}</span>
        <p>{ui('instance.rememberRunHelp')}</p>
      </div>
      <div className="field-control">
        <FieldInput id="instance-remember" label={ui('instance.rememberRun')} value={startupEdits.edits.remember?.value ?? startupRemember ?? false} disabled={startupRemember === undefined} onChange={value => startupQueue.change('remember', value)}/>
        <EditStatus id="instance-remember" edit={startupEdits.edits.remember}/>
      </div>
    </div>
  </Panel>

  // 任务级说明（Task.<task>.help）：作为卡片列首卡，与参数卡同宽同层。
  const taskHelp = t(`Task.${task}.help`)
  const taskHelpBlock = taskHelp && taskHelp !== 'help' && !taskHelp.startsWith('Task.')
    ? <Panel className="task-help-panel"><p className="task-help">{htmlToPlainText(taskHelp)}</p></Panel>
    : null

  const groupCardsBlock = <div className="config-groups">{taskHelpBlock}{startupPanel}{task === 'Alas' && !search && <AccountPanel key={instance} instance={instance}/>} {groupCards}</div>
  const groupNav = <nav className="group-nav">
    {visibleGroups.map(({group}) => (
      <a
        key={group}
        href={`#group-${group}`}
        onClick={event => {
          event.preventDefault()
          const target = document.getElementById(`group-${group}`)
          if (target) smoothScrollToElement(target)
        }}
      >
        {t(`${group}._info.name`)}
      </a>
    ))}
  </nav>

  // 目录与调度器是两列，不是一栏里的两块：目录常驻设置区右侧，调度器独占一列。
  // 调度器列就是总览页那一个 ModernRail，不换外壳、不套 panel；
  // 停靠边与显隐都来自界面设置（schedulerPositionPrefs / railPrefs）。
  const directory = <aside ref={directoryRef} id="task-config-directory" role={popout === 'directory' ? 'dialog' : undefined} aria-modal={popout === 'directory' || undefined} tabIndex={popout === 'directory' ? -1 : undefined} className="task-config-directory task-rail-directory instance-page-rail" aria-label={ui('task.groupNav')} onContextMenu={event => event.preventDefault()}>
    <div className="rail-section-heading">
      <div><ListTree size={15}/><span>{ui('task.groupNav')}</span></div>
      {popout === 'directory' && <button type="button" className="icon-button rail-pop-close" aria-label={ui('nav.close')} onClick={() => setPopout(null)}><X size={15}/></button>}
    </div>
    {groupNav}
  </aside>

  const rail = <ModernRail instance={instance} data={railData} onData={setRailData}/>

  const configToolbar = showConfigToolbar && <div className="config-toolbar">
      <div className="input-icon">
        <Search size={17} />
        <Input placeholder={ui('task.searchConfigPlaceholder')} aria-label={ui('task.searchConfig')} value={search} onChange={event => setSearch(event.target.value)}/>
      </div>
    </div>

  const head = <>
    {configError && <ErrorBox message={configError} retry={reload}/>}
    {task === 'Alas' && startupError && <ErrorBox message={startupError} retry={reloadStartup}/>}
    {error && <ErrorBox message={error}/>}
    {storageError && <ErrorBox message={storageError} />}
    {configToolbar}
  </>

  const groupsSection = !hasGroups ? (
    <>{taskHelpBlock}{(search || !tool) && <Empty icon={<Settings2 size={30} />} title={ui(search ? 'task.noConfigFound' : 'task.noConfig')}>
      {search ? ui('task.tryOtherKeyword') : ui('task.viewRelated')}
    </Empty>}</>
  ) : groupCardsBlock

  const toolPanel = task === 'OpsiSimulator'
    ? <OpsiSimulatorPanel key={instance} instance={instance} beforeStart={() => queue.settled()}/>
    : tool && <Panel className="tool-log-panel" aria-label={ui('monitor.logs')}>
    <PanelHeading title={ui('monitor.logs')} icon={<Terminal size={18}/>} actions={
      <button className="button primary" onClick={() => setConfirmRun(true)} disabled={busy || connection !== 'ready'}>
        <Play size={16}/>{ui('task.runTool')}
      </button>
    }/>
    <LogPanel />
  </Panel>

  // 现代版式的任务详细设置：参数卡在中列，目录与调度器各占一列，页名由顶栏居中显示。
  // 调度器列的宽度沿用总览页那套 `--modern-rail-width`，边上挂同一个拖拽把手。
  return <>
    <div
      ref={setGridNode}
      className={`task-config-page task-config-modern${schedulerPosition === 'left' ? ' rail-left' : ''}${railVisibility === 'hidden' ? ' rail-hidden' : ''}${directoryFolded ? ' directory-folded' : ''}${railFolded ? ' rail-folded' : ''}${popout ? ` pop-${popout}` : ''}`}
      style={layout.railWidth ? ({'--modern-rail-width': `${layout.railWidth}px`} as CSSProperties) : undefined}
    >
      <PageTitle title={t(`Task.${task}.name`)} placement="screen-reader"/>
      <div className="task-config-settings">
        {/* 换任务时重挂内容列，触发该任务的卡片入场。 */}
        <div className="task-config-settings-inner" key={task}>{head}{groupsSection}{scorePanel}{toolPanel}</div>
      </div>
      {directory}
      <div ref={railRef} id="task-config-rail" role={popout === 'rail' ? 'dialog' : undefined} aria-modal={popout === 'rail' || undefined} tabIndex={popout === 'rail' ? -1 : undefined} className="task-config-rail-slot" aria-label={ui('scheduler.rail')}>
        <div className="instance-page-rail-wrap">
          {rail}
          <ModernRailResizeHandle side={schedulerPosition}/>
          {popout === 'rail' && <button type="button" className="icon-button rail-pop-close rail-pop-close-rail" aria-label={ui('nav.close')} onClick={() => setPopout(null)}><X size={15}/></button>}
        </div>
      </div>
      {/* 窄屏折叠后的边缘浮标：唤出对应侧列的抽屉；手动隐藏调度器栏（界面设置）时不给浮标 */}
      {directoryFolded && <button type="button" className="rail-fold-chip rail-fold-chip-directory" aria-label={ui('task.groupNav')} title={ui('task.groupNav')} aria-haspopup="dialog" aria-controls="task-config-directory" aria-expanded={popout === 'directory'} onClick={event => {openerRef.current = event.currentTarget; setPopout(current => current === 'directory' ? null : 'directory')}}><ListTree size={16}/></button>}
      {railFolded && railVisibility === 'shown' && <button type="button" className={`rail-fold-chip rail-fold-chip-rail${schedulerPosition === 'left' ? ' chip-left' : ' chip-right'}`} aria-label={ui('scheduler.rail')} title={ui('scheduler.rail')} aria-haspopup="dialog" aria-controls="task-config-rail" aria-expanded={popout === 'rail'} onClick={event => {openerRef.current = event.currentTarget; setPopout(current => current === 'rail' ? null : 'rail')}}>{schedulerPosition === 'left' ? <PanelLeft size={16}/> : <PanelRight size={16}/>}</button>}
      {popout && <div className="task-config-pop-backdrop" onClick={() => setPopout(null)}/>}
    </div>
    {modal}
  </>
}
