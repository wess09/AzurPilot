import {useCallback, useEffect, useMemo, useRef, useState, type FormEvent} from 'react'
import {useParams} from 'react-router-dom'
import {Download, Fuel, RefreshCw, Search} from 'lucide-react'
import {api} from '../api/client'
import type {ResourceFlowEntry, ResourceFlowReport} from '../api/types'
import {useApp, useConnection} from '../app/context'
import {Checkbox, Select} from '../components/FormControls'
import {Empty, ErrorBox, Loading, PageTitle} from '../components/ui'
import {Input} from '../components/ui/input'
import {downloadCsv} from '../components/statisticsData'
import {localizeFlowReport, statTextTranslator} from '../components/statisticsText'
import {resourceIcons} from '../components/StatisticsTable'
import {Sankey} from '../resources/Sankey'
import type {UiKey} from '../i18n'
import '../resources/resources.css'

const resourceKeys: Record<string, UiKey> = {Oil: 'resource.Oil', Coin: 'resource.Coin', Gem: 'resource.Gem', Cube: 'resource.Cube', Pt: 'resource.Pt', Core: 'resource.Core', Medal: 'resource.Medal', Merit: 'resource.Merit', GuildCoin: 'resource.GuildCoin', ActionPoint: 'resource.ActionPoint', YellowCoin: 'resource.YellowCoin', PurpleCoin: 'resource.PurpleCoin', Chip: 'resource.Chip', Food: 'flow.food', URPt: 'flow.urPt', FurnitureCoin: 'flow.furnitureCoin', GachaTicket: 'flow.gachaTicket'}

function OilControl({instance, value}: {instance: string; value: ResourceFlowReport['oilControl']}) {
  const {ui} = useApp(), [enable, setEnable] = useState(value.enable), [target, setTarget] = useState(String(value.target))
  const [state, setState] = useState(''), [error, setError] = useState('')
  const [dirty, setDirty] = useState(false)
  useEffect(() => {if (!dirty) {setEnable(value.enable); setTarget(String(value.target))}}, [value.enable, value.target, dirty])
  async function save(event: FormEvent) {
    event.preventDefault()
    const number = Number(target)
    if (!Number.isInteger(number) || number < 1000 || number > 24999) {setError(ui('flow.targetInvalid')); return}
    setState('saving'); setError('')
    try {
      const config = await api.request('config.get', {instance})
      await api.request('config.patch', {instance, revision: config.revision, changes: [{path: 'General.OilControl.Enable', value: enable}, {path: 'General.OilControl.Target', value: number}]})
      setState('saved')
    } catch (error) {setError((error as Error).message); setState('')}
  }
  return <section className="resource-panel oil-control"><div><h2><Fuel size={17}/>{ui('flow.oil')}</h2><p className="muted">{ui('flow.oilHint')}</p></div><form onSubmit={save}>
    <Checkbox checked={enable} disabled={state === 'saving'} onChange={event => {setEnable(event.target.checked); setDirty(true); setState('')}}>{ui('flow.oilEnable')}</Checkbox>
    <label>{ui('flow.oilTarget')}<Input required disabled={state === 'saving'} type="number" min="1000" max="24999" step="1" value={target} onChange={event => {setTarget(event.target.value); setDirty(true); setState('')}}/></label>
    <button className="button secondary" disabled={state === 'saving'}>{ui('flow.save')}</button><span role="status">{state === 'saving' ? ui('flow.saving') : state === 'saved' ? ui('flow.saved') : ''}</span>
  </form>{error && <ErrorBox message={error}/>}</section>
}

export function ResourceManagement() {
  const {instance = ''} = useParams(), {ui, t, language} = useApp(), connection = useConnection()
  const [days, setDays] = useState('7'), [draftStart, setDraftStart] = useState(''), [draftEnd, setDraftEnd] = useState('')
  const [interval, setInterval] = useState<{start?: string; end?: string}>({})
  const [resource, setResource] = useState('Oil'), [task, setTask] = useState(''), [offset, setOffset] = useState(0), [search, setSearch] = useState('')
  const [report, setReport] = useState<ResourceFlowReport>(), [error, setError] = useState(''), [refresh, setRefresh] = useState(0), [busy, setBusy] = useState(false), [exporting, setExporting] = useState(false)
  const generation = useRef(0)
  useEffect(() => {setOffset(0); setError('')}, [instance])
  useEffect(() => {
    if (connection !== 'ready') return
    const owner = ++generation.current
    let active = true, pending = false, running = false
    async function load() {
      if (running) {pending = true; return}
      running = true; setBusy(true)
      try {
        const result = await api.request('statistics.resourceFlows', {instance, days: Number(days) || 7, ...interval, resource: resource || null, task: task || null, offset, limit: 100})
        if (active && generation.current === owner) {setReport(result); setError('')}
      } catch (error) {if (active && generation.current === owner) setError((error as Error).message)}
      finally {running = false; if (active) {setBusy(false); if (pending) {pending = false; void load()}}}
    }
    void load()
    const unsubscribe = api.onEvent(event => {if (event.topic === 'statistics' && (event.data as {instance?: string})?.instance === instance) void load()})
    return () => {active = false; unsubscribe()}
  }, [connection, instance, days, interval, resource, task, offset, refresh])
  /* 物品名、分组与用途来自后端中文，显示前译成界面语言。 */
  const shown = useMemo(() => report?.instance === instance ? localizeFlowReport(report, language) : undefined, [report, instance, language])
  const resourceLabel = useCallback((key: string) => {
    return resourceKeys[key] ? ui(resourceKeys[key]) : shown?.resources.find(item => item.key === key)?.label ?? key
  }, [ui, shown])
  const taskLabel = useCallback((key: string) => key === 'Unattributed' ? ui('flow.unattributed') : key === 'OilControl' ? ui('flow.oil') : t(`Task.${key}.name`), [t, ui])
  const evidence = (key: ResourceFlowEntry['evidence']) => ui(key === 'adjustment' ? 'flow.adjustment' : key === 'observed' ? 'flow.observed' : key === 'recognition' ? 'flow.recognition' : 'flow.confirmed')
  const pick = useCallback((key: string, task?: string) => {setResource(key); setTask(task ?? ''); setOffset(0)}, [])
  async function exportEntries() {
    if (!shown || exporting || busy) return
    const source = shown
    setExporting(true)
    try {
      const rows: ResourceFlowEntry[] = []
      for (let offset = 0; ; offset += 1000) {
        const page = await api.request('statistics.resourceFlows', {instance, start: source.start, end: source.end, resource: resource || null, task: task || null, offset, limit: 1000, through_id: source.throughId})
        rows.push(...page.entries)
        if (offset + page.entries.length >= page.total || !page.entries.length) break
      }
      downloadCsv(`${instance}-resource-flows`, [[ui('flow.time'), ui('flow.resource'), ui('flow.task'), ui('flow.operation'), ui('flow.net'), ui('flow.evidence')], ...rows.map(entry => [entry.ts, resourceLabel(entry.resource), taskLabel(entry.task), statTextTranslator(language, source.glossary)(entry.operation), entry.amount, evidence(entry.evidence)])])
    } catch (error) {setError((error as Error).message)} finally {setExporting(false)}
  }
  const number = (value: number | null) => value === null ? '—' : value.toLocaleString()
  return <div className="resource-management">
    <PageTitle title={ui('nav.resources')} actions={<><button className="button secondary" disabled={busy} onClick={() => setRefresh(value => value + 1)}><RefreshCw size={15}/>{ui('stats.refresh')}</button><button className="button secondary" disabled={!shown || !shown.total || exporting || busy || !!error} onClick={exportEntries}><Download size={15}/>{ui('flow.export')}</button></>}/>
    <section className="resource-panel resource-filters">
      <p className="muted resource-intro">{ui('flow.hint')}</p>
      <label>{ui('flow.range')}<Select value={days} onChange={event => {setDays(event.target.value); if (event.target.value !== 'custom') setInterval({}); setOffset(0)}}><option value="1">{ui('flow.day')}</option><option value="7">{ui('flow.week')}</option><option value="30">{ui('flow.month')}</option><option value="custom">{ui('flow.custom')}</option></Select></label>
      {days === 'custom' && <form onSubmit={event => {event.preventDefault(); setInterval({start: draftStart, end: draftEnd}); setOffset(0)}}><label>{ui('flow.start')}<Input required type="datetime-local" value={draftStart} onChange={event => setDraftStart(event.target.value)}/></label><label>{ui('flow.end')}<Input required type="datetime-local" value={draftEnd} onChange={event => setDraftEnd(event.target.value)}/></label><button className="button secondary">{ui('flow.apply')}</button></form>}
      <label>{ui('flow.resource')}<Select value={resource} onChange={event => {setResource(event.target.value); setOffset(0)}}><option value="">{ui('flow.allResources')}</option>{shown?.resources.map(item => <option key={item.key} value={item.key}>{resourceLabel(item.key)}</option>)}</Select></label>
      <label>{ui('flow.task')}<Select value={task} onChange={event => {setTask(event.target.value); setOffset(0)}}><option value="">{ui('flow.allTasks')}</option>{shown?.tasks.map(key => <option key={key} value={key}>{taskLabel(key)}</option>)}</Select></label>
    </section>
    {error && <ErrorBox message={error} retry={() => setRefresh(value => value + 1)}/>}
    {!shown && !error && <Loading/>}
    {shown && <>
      <OilControl key={instance} instance={instance} value={shown.oilControl}/>
      <section className="resource-panel"><h2>{ui('flow.sankey')}</h2><p className="muted">{ui('flow.units')}</p>
        {shown.flows.length ? <Sankey report={shown} resourceLabel={resourceLabel} taskLabel={taskLabel} onPick={pick}/> : <Empty title={ui('flow.empty')}>{ui('flow.emptyHint')}</Empty>}
      </section>
      <section className="resource-panel"><div className="resource-heading"><h2>{ui('flow.inventory')}</h2><label className="resource-search"><Search size={16}/><Input className="w-56" aria-label={ui('flow.search')} placeholder={ui('flow.search')} value={search} onChange={event => setSearch(event.target.value)}/></label></div>
        <div className="resource-table-wrap"><table><thead><tr><th>{ui('flow.resource')}</th><th>{ui('flow.current')}</th><th>{ui('flow.income')}</th><th>{ui('flow.expense')}</th><th>{ui('flow.net')}</th><th>{ui('flow.adjustment')}</th></tr></thead><tbody>
          {shown.resources.filter(item => `${resourceLabel(item.key)} ${item.key} ${item.group}`.toLowerCase().includes(search.toLowerCase())).map(item => <tr key={item.key} className={resource === item.key ? 'selected' : ''}><th><button className="resource-pick" onClick={() => {setResource(item.key); setTask(''); setOffset(0)}}>{resourceIcons[item.label] && <img src={resourceIcons[item.label]} alt=""/>}{resourceLabel(item.key)}</button></th><td title={item.observedAt ?? ''}>{number(item.current)}</td><td className="resource-income">{number(item.income)}</td><td>{number(item.expense)}</td><td>{number(item.income - item.expense)}</td><td>{number(item.adjustment)}</td></tr>)}
        </tbody></table></div>
      </section>
      <section className="resource-panel"><div className="resource-heading"><h2>{ui('flow.details')}</h2><span className="muted">{ui('flow.count', {count: shown.total})}</span></div><p className="muted">{ui('flow.accounting')}</p>
        <div className="resource-table-wrap"><table><thead><tr>{['flow.time', 'flow.resource', 'flow.task', 'flow.operation', 'flow.net', 'flow.evidence'].map(key => <th key={key}>{ui(key as 'flow.time')}</th>)}</tr></thead><tbody>
          {shown.entries.map(entry => <tr key={entry.id}><td>{entry.ts.slice(0, 19)}</td><td>{resourceLabel(entry.resource)}</td><td><button onClick={() => {setTask(entry.task); setOffset(0)}}>{taskLabel(entry.task)}</button></td><td>{entry.operation}</td><td className={entry.amount > 0 ? 'resource-income' : ''}>{entry.amount > 0 ? '+' : ''}{number(entry.amount)}</td><td><span className={`resource-evidence ${entry.evidence}`}>{evidence(entry.evidence)}</span></td></tr>)}
        </tbody></table></div>
        {!shown.total && <p className="muted">{ui('flow.empty')}</p>}
        <div className="resource-pagination"><button className="button secondary" disabled={!offset || busy} onClick={() => setOffset(value => Math.max(0, value - 100))}>{ui('flow.prev')}</button><span>{Math.floor(offset / 100) + 1} / {Math.max(1, Math.ceil(shown.total / 100))}</span><button className="button secondary" disabled={offset + 100 >= shown.total || busy} onClick={() => setOffset(value => value + 100)}>{ui('flow.next')}</button></div>
      </section>
    </>}
  </div>
}
