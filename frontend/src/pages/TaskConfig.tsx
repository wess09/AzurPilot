import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'
import { useParams } from 'react-router-dom'
import { Play, Search, Settings2, Ship, Terminal } from 'lucide-react'
import { api } from '../api/client'
import type { Config } from '../api/types'
import { useApp, useConnection } from '../app/context'
import { usesLegacyLayout } from '../app/theme'
import { Empty, ErrorBox, Loading, Modal, PageTitle } from '../components/ui'
import { LogPanel } from '../components/LogPanel'
import { FieldInput } from '../components/FieldInput'
import { RestrictedLuaEditor } from '../components/RestrictedLuaEditor'
import { ShopStrategyHelp } from '../components/ShopStrategyHelp'
import { StorageField } from '../components/StorageField'
import { editor, prepareValue } from '../config/editors'
import { EditStatus } from '../components/EditStatus'
import { isFieldVisible } from './configVisibility'

export function TaskConfig() {
  const {instance = '', task = ''} = useParams()
  const {schema, t, ui, notify, language, theme} = useApp()
  const connection = useConnection()
  const [config, setConfig] = useState<Config>()
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmRun, setConfirmRun] = useState(false)
  const [shopModeError, setShopModeError] = useState('')

  const queue = editor(`config:${instance}`)
  const {edits, storageError} = useSyncExternalStore(queue.subscribe, queue.getSnapshot)
  const legacy = usesLegacyLayout(theme)
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

  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    const confirmed = queue.confirmed()
    void api.request('config.get', {instance}).then(value => {
      if (active) { setConfig(value); queue.reconcile(confirmed); setError('') }
    }).catch(error => { if (active) setError(error.message) })
    return () => { active = false }
  }, [connection, instance, task, queue])
  useEffect(() => { setShopModeError('') }, [instance, task])

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
  const showConfigToolbar = task !== 'FleetInfo' && Boolean(groups) && (visibleGroups.length > 0 || Boolean(search))

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
      {group === 'ShopAdvanced' && (
        <ShopStrategyHelp task={task} language={language}/>
      )}
      {visible.map(([arg, field]) => {
        const path = `${task}.${group}.${arg}`
        const edit = edits[path]
        const value = edit ? edit.value : config.values[task]?.[group]?.[arg] ?? field.value
        const label = t(`${group}.${arg}.name`)
        const help = t(`${group}.${arg}.help`)
        const readonly = ['disabled', 'readonly'].includes(field.display ?? '') || ['storage', 'stored', 'state', 'lock'].includes(field.type)
        const restrictedLua = field.mode === 'restricted_lua'
        const shopMode = group === 'ShopAdvanced' && arg === 'Mode'
        // 「立刻运行」只对每个任务的调度时间有意义，其他时间字段（如仪表盘记录时间）不显示。
        const runNow = group === 'Scheduler' && arg === 'NextRun' && !readonly
        const isMultiline = ['textarea', 'task_priority', 'yaml', 'storage'].includes(field.type) || field.mode === 'yaml' || restrictedLua

        return (
          <div className={`field-row ${isMultiline ? 'field-row-multiline' : ''}`} key={arg}>
            <div className="field-label">
              <label htmlFor={path}>
                {label}
                {readonly && <span className="small-label">{ui('task.readonly')}</span>}
              </label>
              {help && help !== 'help' && help !== arg && <p>{help.replace(/<[^>]*>/g, '')}</p>}
            </div>
            <div className="field-control">
              {field.type === 'storage' ? (
                <StorageField value={value} disabled={false} onClear={() => queue.change(path, {})} />
              ) : restrictedLua ? (
                <RestrictedLuaEditor
                  id={path}
                  value={String(value ?? '')}
                  draftKey={`${instance}.${path}`}
                  label={label}
                  disabled={readonly}
                  offline={connection !== 'ready'}
                  onCheck={script => api.request('shop_strategy.validate', {instance, task: task as 'EventShop' | 'ShopFrequent' | 'ShopOnce' | 'PrivateQuarters' | 'OpsiShop' | 'OpsiVoucher', script})}
                  onApply={async script => {
                    setConfig(await api.request('config.patch', {instance, changes: [{path, value: script}]}))
                    setShopModeError('')
                  }}
                />
              ) : (
                <FieldInput
                  id={path}
                  value={value}
                  mode={field.mode}
                  type={field.type === 'input' && typeof field.value === 'number' ? 'number' : field.type}
                  options={field.option}
                  disabled={readonly}
                  preserveText
                  invalid={edit?.status === 'error' || (shopMode && !!shopModeError)}
                  label={label}
                  translateOption={option => t(`${group}.${arg}.${option}`)}
                  onChange={next => {
                    if (shopMode && next === 'advanced') {
                      const script = String(config.values[task]?.ShopAdvanced?.Script ?? '')
                      if (!script.trim()) {
                        setShopModeError(ui('script.modeRequiresScript'))
                        return
                      }
                    }
                    if (shopMode) setShopModeError('')
                    const {payload, text, error} = prepareValue(next, field)
                    queue.change(path, text ?? next, payload, error)
                  }}
                />
              )}
              {runNow && (
                <div className="field-actions">
                  <button type="button" className="button subtle" disabled={connection !== 'ready'}
                    onClick={() => {
                      // 按钮等同清空该字段：空时间按参数默认值提交，调度器下一轮即把任务视为待运行。
                      const {payload, text, error} = prepareValue('', field)
                      queue.change(path, text ?? '', payload, error)
                    }}><Play size={15}/>{ui('task.runNow')}</button>
                </div>
              )}
              {shopMode && shopModeError && !edit ? (
                <div id={`${path}-status`} className="edit-status edit-error" role="alert">{shopModeError}</div>
              ) : <EditStatus id={path} edit={edit} retry={queue.retry} />}
            </div>
          </div>
        )
      })}
    </section>
  ))}
    {search && !visibleGroups.length && <Empty icon={<Search size={26} />} title={ui('task.noConfigFound')}>{ui('task.tryOtherKeyword')}</Empty>}
  </>

  const hasGroups = task !== 'FleetInfo' && Boolean(groups) && visibleGroups.length > 0
  const groupCardsBlock = <div className="config-groups">{groupCards}</div>
  const groupNav = <nav className="group-nav">
    {visibleGroups.map(({group}) => (
      <a
        key={group}
        href={`#group-${group}`}
        onClick={event => {
          event.preventDefault()
          document.getElementById(`group-${group}`)?.scrollIntoView({behavior: 'smooth', block: 'start'})
        }}
      >
        {t(`${group}._info.name`)}
      </a>
    ))}
  </nav>

  const head = <>
    {error && <ErrorBox message={error} retry={reload} />}
    {storageError && <ErrorBox message={storageError} />}
    {showConfigToolbar && <div className="config-toolbar">
      <div className="input-icon">
        <Search size={17} />
        <input placeholder={ui('task.searchConfigPlaceholder')} aria-label={ui('task.searchConfig')} value={search} onChange={event => setSearch(event.target.value)} />
      </div>
    </div>}
  </>

  const groupsSection = task === 'FleetInfo' ? (
    <FleetInfo value={config.values.FleetInfo?.FleetInfo?.Result} />
  ) : !hasGroups ? (
    (search || !tool) && <Empty icon={<Settings2 size={30} />} title={ui('task.noConfig')}>
      {search ? ui('task.tryOtherKeyword') : ui('task.viewRelated')}
    </Empty>
  ) : groupCardsBlock

  const toolPanel = tool && <section className="panel tool-log-panel" aria-label={ui('monitor.logs')}>
    <div className="panel-heading">
      <div><Terminal size={18}/><h2>{ui('monitor.logs')}</h2></div>
      <button className="button primary" onClick={() => setConfirmRun(true)} disabled={busy || connection !== 'ready'}>
        <Play size={16}/>{ui('task.runTool')}
      </button>
    </div>
    <LogPanel />
  </section>

  // 旧版的任务详细设置：参数卡在左、分组导航在右，页名由顶栏居中显示。
  // 这里不放调度器与任务计划 —— 旧版把它们留在总览页。
  if (legacy) return <>
    <div className={`task-config-legacy${hasGroups ? '' : ' no-nav'}`}>
      <h1 className="legacy-sr-title">{t(`Task.${task}.name`)}</h1>
      <div className="task-config-settings">{head}{groupsSection}{toolPanel}</div>
      {hasGroups && groupNav}
    </div>
    {modal}
  </>

  return <>
    <PageTitle
      title={t(`Task.${task}.name`)}
    />
    {head}
    {hasGroups ? <div className="config-layout">{groupNav}{groupCardsBlock}</div> : groupsSection}
    {toolPanel}
    {modal}
  </>
}

function FleetInfo({value}: {value: unknown}) {
  const {ui} = useApp()
  if (!value || (typeof value === 'object' && !Object.keys(value).length)) return <Empty icon={<Ship size={32}/>} title={ui('fleet.emptyTitle')}>{ui('fleet.emptyHint')}</Empty>
  let fleets: Record<string, Record<string, Array<{name: string; level?: number} | string>>>
  try {fleets = typeof value === 'string' ? JSON.parse(value) : value} catch {return <ErrorBox message={ui('fleet.invalid')}/>}
  const columns = {vanguard: ui('fleet.vanguard'), main: ui('fleet.main'), submarine: ui('fleet.submarine')}
  return <div className="fleet-grid">{[1, 2, 3, 4, 5, 6].map(fleet => <section className="panel" key={fleet}><div className="panel-heading"><h2>{ui('fleet.title', {number: fleet})}</h2><Ship size={18}/></div>{Object.entries(columns).map(([key, label]) => <div className="fleet-column" key={key}><h3>{label}</h3>{fleets[key]?.[fleet]?.length ? fleets[key][fleet].map((ship, index) => <div key={index}><span>{typeof ship === 'string' ? ship : ship.name}</span><small>{typeof ship !== 'string' && ship.level ? `Lv.${ship.level}` : ''}</small></div>) : <p>{ui('fleet.noRecord')}</p>}</div>)}</section>)}</div>
}
