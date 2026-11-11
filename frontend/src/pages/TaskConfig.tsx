/**
 * @fileoverview 任务参数设置页面。
 */

import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'
import type { CSSProperties } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ListTree, Play, RotateCcw, Search, Settings2, Terminal } from 'lucide-react'
import { api } from '../api/client'
import type { Config } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { htmlToPlainText } from '../app/htmlText'
import { getLayout, subscribeLayout } from '../app/layout'
import { readRailVisible, subscribeRailVisible } from '../app/railPrefs'
import { readSchedulerPosition, subscribeSchedulerPosition } from '../app/schedulerPositionPrefs'
import { smoothScrollToElement } from '../app/scroll'
import { clearSearchTarget, peekSearchTarget, subscribeSearchTarget } from '../app/searchTarget'
import { Empty, ErrorBox, Loading, Modal } from '../components/ui'
import { Input } from '../components/ui/input'
import { LogPanel } from '../components/LogPanel'
import { MeowfficerScorePanel } from '../components/MeowfficerScorePanel'
import { OpsiSimulatorPanel } from '../components/OpsiSimulatorPanel'
import { FieldInput } from '../components/FieldInput'
import { StorageField } from '../components/StorageField'
import { LegacyRail } from '../components/LegacyRail'
import { LegacyRailResizeHandle } from '../components/LegacyRailResizeHandle'
import { useInstanceOverview } from '../components/useInstanceOverview'
import { editor, prepareValue } from '../config/editors'
import { EditStatus } from '../components/EditStatus'
import { AccountPanel } from '../components/AccountPanel'
import { isFieldVisible } from './configVisibility'
import { FleetInfoPage } from './FleetInfoPage'

export function TaskConfig() {
  const {instance = '', task = ''} = useParams()
  const {schema, t, ui, notify} = useApp()
  const connection = useConnection()
  const railVisibility = useSyncExternalStore(subscribeRailVisible, readRailVisible, readRailVisible)
  const schedulerPosition = useSyncExternalStore(subscribeSchedulerPosition, readSchedulerPosition, readSchedulerPosition)
  // 调度器列的宽度与总览页共用同一个持久化值，拖动任一处另一边跟着变。
  const layout = useSyncExternalStore(subscribeLayout, getLayout, getLayout)
  // 右列现在同时承载目录与调度器，进页面就要拉一份总览数据。
  const [railData, setRailData] = useInstanceOverview(instance, true)
  const [config, setConfig] = useState<Config>()
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmRun, setConfirmRun] = useState(false)

  const queue = editor(`config:${instance}`)
  const {edits, storageError} = useSyncExternalStore(queue.subscribe, queue.getSnapshot, queue.getSnapshot)
  const startupQueue = editor(`startup:${instance}`)
  const startupEdits = useSyncExternalStore(startupQueue.subscribe, startupQueue.getSnapshot, startupQueue.getSnapshot)
  const [startupEnabled, setStartupEnabled] = useState<boolean>()
  const [startupRemember, setStartupRemember] = useState<boolean>()
  const reload = useCallback(async () => {
    try {
      const confirmed = queue.confirmed()
      setConfig(await api.request('config.get', {instance}))
      queue.reconcile(confirmed)
      setError('')
    } catch (error) {
      setError((error as Error).message)
    }
  }, [instance, queue])

  // 字段保存成功后用服务端回传的整份配置替换本地副本。
  useEffect(() => {
    queue.onSaved = data => setConfig(data as Config)
    return () => { queue.onSaved = undefined }
  }, [queue])

  // 启动开关保存成功后用服务端回传的状态替换本地值，队列丢弃已保存条目后开关不回弹。
  useEffect(() => {
    startupQueue.onSaved = data => {
      const value = data as {enabled: boolean; remember: boolean}
      setStartupEnabled(value.enabled)
      setStartupRemember(value.remember)
    }
    return () => { startupQueue.onSaved = undefined }
  }, [startupQueue])

  useEffect(() => {
    if (connection !== 'ready' || task === 'FleetInfo') return
    let active = true
    const confirmed = queue.confirmed()
    void api.request('config.get', {instance}).then(value => {
      if (active) { setConfig(value); queue.reconcile(confirmed); setError('') }
    }).catch(error => { if (active) setError(error.message) })
    return () => { active = false }
  }, [connection, instance, task, queue])
  /* 开关状态取自部署层的运行列表，不在任务配置里。 */
  useEffect(() => {
    if (connection !== 'ready' || task !== 'Alas') return
    let active = true
    const confirmed = startupQueue.confirmed()
    void api.request('startup.get', {instance}).then(value => {
      if (active) { setStartupEnabled(value.enabled); setStartupRemember(value.remember); startupQueue.reconcile(confirmed) }
    }).catch(error => { if (active) setError(error.message) })
    return () => { active = false }
  }, [connection, instance, task, startupQueue])

  async function run() {
    setBusy(true)
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
      // 卡片命中给两段路径（任务.分组），配置项命中给三段；据此选 DOM id 与滚动方式
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
          // 等不到字段（被隐藏或该任务下没有这一项）就放弃，不再重试
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
  if (!config) return error ? <ErrorBox message={error} retry={reload} /> : <Loading />

  const modal = confirmRun && (
    <Modal title={ui('task.runTitle', {task: t(`Task.${task}.name`)})} onClose={() => setConfirmRun(false)}>
      <p>{ui('task.runWarning')}</p>
      <button className="button primary" disabled={busy} onClick={run}>
        <Play size={15} />{ui('task.confirmRun')}
      </button>
    </Modal>
  )

  const groupCards = <>{visibleGroups.map(({group, visible}) => (
    <section className="panel config-group" key={group} id={`group-${group}`}>
      <div className="panel-heading">
        <div>
          <span className="group-indicator" />
          <h2 data-text={t(`${group}._info.name`)}>{t(`${group}._info.name`)}</h2>
        </div>
      </div>
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
              {isMultiline && <EditStatus id={path} edit={edit} retry={queue.retry} queue={queue} />}
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
              {!isMultiline && <EditStatus id={path} edit={edit} retry={queue.retry} queue={queue} />}
            </div>
          </div>
        )
      })}
    </section>
  ))}
  {search && !visibleGroups.length && <Empty icon={<Search size={26} />} title={ui('task.noConfigFound')}>{ui('task.tryOtherKeyword')}</Empty>}
  </>

  const hasGroups = task !== 'FleetInfo' && Boolean(groups) && visibleGroups.length > 0
  // 只有紧凑主题把搜索框并进左列（跳转栏下方），其余主题保持标题下方的原样。
  // 启动开关挂在系统设置（Alas）任务页顶部；搜索时只显示匹配项。
  const startupPanel = task === 'Alas' && !search && <section className="panel config-group">
    <div className="panel-heading">
      <div>
        <span className="group-indicator"/>
        <h2>{ui('instance.startup')}</h2>
      </div>
    </div>
    <div className="field-row">
      <div className="field-label">
        <span className="field-name">{ui('instance.autoRun')}</span>
        <p>{ui('instance.autoRunHelp')}</p>
      </div>
      <div className="field-control">
        <FieldInput id="instance-startup" label={ui('instance.autoRun')} value={startupEdits.edits.enabled?.value ?? startupEnabled ?? false} disabled={startupEnabled === undefined} onChange={value => startupQueue.change('enabled', value)}/>
        <EditStatus id="instance-startup" edit={startupEdits.edits.enabled} retry={startupQueue.retry} queue={startupQueue}/>
      </div>
    </div>
    <div className="field-row">
      <div className="field-label">
        <span className="field-name">{ui('instance.rememberRun')}</span>
        <p>{ui('instance.rememberRunHelp')}</p>
      </div>
      <div className="field-control">
        <FieldInput id="instance-remember" label={ui('instance.rememberRun')} value={startupEdits.edits.remember?.value ?? startupRemember ?? false} disabled={startupRemember === undefined} onChange={value => startupQueue.change('remember', value)}/>
        <EditStatus id="instance-remember" edit={startupEdits.edits.remember} retry={startupQueue.retry} queue={startupQueue}/>
      </div>
    </div>
  </section>

  /* 任务级说明（Task.<task>.help）：作为卡片列首卡，与参数卡同宽同层。 */
  const taskHelp = t(`Task.${task}.help`)
  const taskHelpBlock = taskHelp && taskHelp !== 'help' && !taskHelp.startsWith('Task.')
    ? <section className="panel task-help-panel"><p className="task-help">{htmlToPlainText(taskHelp)}</p></section>
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
  // 调度器列就是总览页那一个 LegacyRail，不换外壳、不套 panel；
  // 停靠边与显隐都来自界面设置（schedulerPositionPrefs / railPrefs）。
  const directory = <aside className="task-config-directory task-rail-directory instance-page-rail" aria-label={ui('task.groupNav')} onContextMenu={event => event.preventDefault()}>
    <div className="rail-section-heading">
      <div><ListTree size={15}/><span>{ui('task.groupNav')}</span></div>
    </div>
    {groupNav}
  </aside>

  const rail = <LegacyRail instance={instance} data={railData} onData={setRailData}/>

  const configToolbar = showConfigToolbar && <div className="config-toolbar">
      <div className="input-icon">
        <Search size={17} />
        <Input placeholder={ui('task.searchConfigPlaceholder')} aria-label={ui('task.searchConfig')} value={search} onChange={event => setSearch(event.target.value)}/>
      </div>
    </div>

  const head = <>
    {error && <ErrorBox message={error} retry={reload} />}
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
    : tool && <section className="panel tool-log-panel" aria-label={ui('monitor.logs')}>
    <div className="panel-heading">
      <div><Terminal size={18}/><h2>{ui('monitor.logs')}</h2></div>
      <button className="button primary" onClick={() => setConfirmRun(true)} disabled={busy || connection !== 'ready'}>
        <Play size={16}/>{ui('task.runTool')}
      </button>
    </div>
    <LogPanel />
  </section>

  // 旧版的任务详细设置：参数卡在中列，目录与调度器各占一列，页名由顶栏居中显示。
  // 调度器列的宽度沿用总览页那套 `--legacy-rail-width`，边上挂同一个拖拽把手。
  return <>
    <div
      className={`task-config-legacy${schedulerPosition === 'left' ? ' rail-left' : ''}${railVisibility === 'hidden' ? ' rail-hidden' : ''}`}
      style={layout.legacyRailWidth ? ({'--legacy-rail-width': `${layout.legacyRailWidth}px`} as CSSProperties) : undefined}
    >
      <h1 className="legacy-sr-title">{t(`Task.${task}.name`)}</h1>
      <div className="task-config-settings">
        {/* 换任务时重挂一次，让内容列的淡入重放。 */}
        <div className="task-config-settings-inner" key={task}>{head}{groupsSection}{scorePanel}{toolPanel}</div>
      </div>
      {directory}
      <div className="task-config-rail-slot" aria-label={ui('scheduler.rail')}>
        <div className="instance-page-rail-wrap">
          {rail}
          <LegacyRailResizeHandle side={schedulerPosition}/>
        </div>
      </div>
    </div>
    {modal}
  </>
}
