/**
 * @fileoverview 资源管理页：物资收支流水、库存概览、大世界流向图与油量控制。
 */

import {Button} from '../components/ui/button'
import {Table, TableBody, TableCell, TableHead, TableHeader, TableRow} from '../components/ui/table'
import {useCallback, useEffect, useMemo, useRef, useState, type FormEvent} from 'react'
import {useParams} from 'react-router-dom'
import {Download, Fuel, RefreshCw, Search} from 'lucide-react'
import {api} from '../api/client'
import type {ResourceFlowEntry, ResourceFlowReport} from '../api/types'
import {useApp, useConnection} from '../app/context'
import {Select, SelectContent, SelectItem, SelectTrigger, SelectValue} from '../components/official-ui/select'
import {Checkbox} from '../components/official-ui/checkbox'
import {Label} from '../components/ui/label'
import {Empty, ErrorBox, Loading} from '../components/ui'
import {Input} from '../components/official-ui/input'
import {downloadCsv} from '../components/statisticsData'
import {localizeFlowReport, statTextTranslator} from '../components/statisticsText'
import {resourceIcons} from '../components/StatisticsTable'
import {Sankey} from '../resources/Sankey'
import type {UiKey} from '../i18n'
import '../resources/resources.css'

const resourceKeys: Record<string, UiKey> = {Oil: 'resource.Oil', Coin: 'resource.Coin', Gem: 'resource.Gem', Cube: 'resource.Cube', Pt: 'resource.Pt', Core: 'resource.Core', Medal: 'resource.Medal', Merit: 'resource.Merit', GuildCoin: 'resource.GuildCoin', ActionPoint: 'resource.ActionPoint', YellowCoin: 'resource.YellowCoin', PurpleCoin: 'resource.PurpleCoin', Chip: 'resource.Chip', Food: 'flow.food', URPt: 'flow.urPt', FurnitureCoin: 'flow.furnitureCoin', GachaTicket: 'flow.gachaTicket'}

/**
 * 油量控制面板：开关与目标值作为本地草稿编辑，保存时写入配置 General.OilControl.Enable/Target。
 * 外部 value 变化只在未编辑（非 dirty）时回填输入框，不覆盖用户正在改的草稿。
 */
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
    <span className="flex items-center gap-3"><Checkbox id="resource-oil-enable" checked={enable} disabled={state === 'saving'} onCheckedChange={next => {setEnable(next === true); setDirty(true); setState('')}}/><Label htmlFor="resource-oil-enable">{ui('flow.oilEnable')}</Label></span>
    <label>{ui('flow.oilTarget')}<Input required disabled={state === 'saving'} type="number" min="1000" max="24999" step="1" value={target} onChange={event => {setTarget(event.target.value); setDirty(true); setState('')}}/></label>
    <Button variant="outline" disabled={state === 'saving'}>{ui('flow.save')}</Button><span role="status">{state === 'saving' ? ui('flow.saving') : state === 'saved' ? ui('flow.saved') : ''}</span>
  </form>{error && <ErrorBox message={error}/>}</section>
}

/**
 * 资源管理页：按时间范围与资源/任务筛选收支流水，支持分页浏览、库存概览与 CSV 导出。
 * 请求带代号防串台：筛选切换后旧响应作废，加载中的重复触发合并为一次补跑。
 */
export function ResourceManagement() {
  const {instance = ''} = useParams(), {ui, t, language} = useApp(), connection = useConnection()
  const [days, setDays] = useState('7'), [draftStart, setDraftStart] = useState(''), [draftEnd, setDraftEnd] = useState('')
  const [interval, setInterval] = useState<{start?: string; end?: string}>({})
  const [resource, setResource] = useState('Oil'), [task, setTask] = useState(''), [offset, setOffset] = useState(0), [search, setSearch] = useState('')
  const [report, setReport] = useState<ResourceFlowReport>(), [error, setError] = useState(''), [refresh, setRefresh] = useState(0), [busy, setBusy] = useState(false), [exporting, setExporting] = useState(false)
  const generation = useRef(0)
  useEffect(() => {setOffset(0); setError('')}, [instance])
  // 请求带代号（owner 对比 generation）：筛选变化触发新请求后，落在半途的旧响应直接丢弃；
  // 加载中再触发只在 pending 记一笔，当前这轮跑完补发一次，避免并发请求互相覆盖结果。
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
  // 物品名、分组与用途来自后端中文，显示前译成界面语言。
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
    {/* 页名由上方分类标签给出，这里只留动作，不再重复标题 */}
    <div className="flex flex-wrap items-center justify-end gap-2.5"><Button variant="outline" disabled={busy} onClick={() => setRefresh(value => value + 1)}><RefreshCw size={15}/>{ui('stats.refresh')}</Button><Button variant="outline" disabled={!shown || !shown.total || exporting || busy || !!error} onClick={exportEntries}><Download size={15}/>{ui('flow.export')}</Button></div>
    <section className="resource-panel resource-filters">
      <p className="muted resource-intro">{ui('flow.hint')}</p>
      <label>{ui('flow.range')}<Select value={days} onValueChange={value => {setDays(value); if (value !== 'custom') setInterval({}); setOffset(0)}}><SelectTrigger aria-label={ui('flow.range')}><SelectValue/></SelectTrigger><SelectContent><SelectItem value="1">{ui('flow.day')}</SelectItem><SelectItem value="7">{ui('flow.week')}</SelectItem><SelectItem value="30">{ui('flow.month')}</SelectItem><SelectItem value="custom">{ui('flow.custom')}</SelectItem></SelectContent></Select></label>
      {days === 'custom' && <form onSubmit={event => {event.preventDefault(); setInterval({start: draftStart, end: draftEnd}); setOffset(0)}}><label>{ui('flow.start')}<Input required type="datetime-local" value={draftStart} onChange={event => setDraftStart(event.target.value)}/></label><label>{ui('flow.end')}<Input required type="datetime-local" value={draftEnd} onChange={event => setDraftEnd(event.target.value)}/></label><Button variant="outline">{ui('flow.apply')}</Button></form>}
      <label>{ui('flow.resource')}<Select value={resource || '__all__'} onValueChange={value => {setResource(value === '__all__' ? '' : value); setOffset(0)}}><SelectTrigger aria-label={ui('flow.resource')}><SelectValue/></SelectTrigger><SelectContent><SelectItem value="__all__">{ui('flow.allResources')}</SelectItem>{shown?.resources.map(item => <SelectItem key={item.key} value={item.key}>{resourceLabel(item.key)}</SelectItem>)}</SelectContent></Select></label>
      <label>{ui('flow.task')}<Select value={task || '__all__'} onValueChange={value => {setTask(value === '__all__' ? '' : value); setOffset(0)}}><SelectTrigger aria-label={ui('flow.task')}><SelectValue/></SelectTrigger><SelectContent><SelectItem value="__all__">{ui('flow.allTasks')}</SelectItem>{shown?.tasks.map(key => <SelectItem key={key} value={key}>{taskLabel(key)}</SelectItem>)}</SelectContent></Select></label>
    </section>
    {error && <ErrorBox message={error} retry={() => setRefresh(value => value + 1)}/>}
    {!shown && !error && <Loading/>}
    {shown && <>
      {/* key 换实例即重挂：油量控件的开关/目标值是本地草稿状态，不能把上一个实例的草稿带过去 */}
      <OilControl key={instance} instance={instance} value={shown.oilControl}/>
      <section className="resource-panel"><h2>{ui('flow.sankey')}</h2><p className="muted">{ui('flow.units')}</p>
        {shown.flows.length ? <Sankey report={shown} resourceLabel={resourceLabel} taskLabel={taskLabel} onPick={pick}/> : <Empty title={ui('flow.empty')}>{ui('flow.emptyHint')}</Empty>}
      </section>
      <section className="resource-panel"><div className="resource-heading"><h2>{ui('flow.inventory')}</h2><label className="resource-search"><Search size={16}/><Input className="w-56" aria-label={ui('flow.search')} placeholder={ui('flow.search')} value={search} onChange={event => setSearch(event.target.value)}/></label></div>
        <div className="resource-table-wrap"><Table className="min-w-full whitespace-nowrap tabular-nums"><TableHeader className="sticky top-0 z-10"><TableRow><TableHead>{ui('flow.resource')}</TableHead><TableHead className="text-right">{ui('flow.current')}</TableHead><TableHead className="text-right">{ui('flow.income')}</TableHead><TableHead className="text-right">{ui('flow.expense')}</TableHead><TableHead className="text-right">{ui('flow.net')}</TableHead><TableHead className="text-right">{ui('flow.adjustment')}</TableHead></TableRow></TableHeader><TableBody>
          {shown.resources.filter(item => `${resourceLabel(item.key)} ${item.key} ${item.group}`.toLowerCase().includes(search.toLowerCase())).map(item => <TableRow key={item.key} data-state={resource === item.key ? 'selected' : undefined}><TableHead scope="row"><Button type="button" variant="ghost" size="sm" className="resource-pick" onClick={() => {setResource(item.key); setTask(''); setOffset(0)}}>{resourceIcons[item.label] && <img src={resourceIcons[item.label]} alt=""/>}{resourceLabel(item.key)}</Button></TableHead><TableCell className="text-right" title={item.observedAt ?? ''}>{number(item.current)}</TableCell><TableCell className="resource-income text-right">{number(item.income)}</TableCell><TableCell className="text-right">{number(item.expense)}</TableCell><TableCell className="text-right">{number(item.income - item.expense)}</TableCell><TableCell className="text-right">{number(item.adjustment)}</TableCell></TableRow>)}
        </TableBody></Table></div>
      </section>
      <section className="resource-panel"><div className="resource-heading"><h2>{ui('flow.details')}</h2><span className="muted">{ui('flow.count', {count: shown.total})}</span></div><p className="muted">{ui('flow.accounting')}</p>
        <div className="resource-table-wrap"><Table className="min-w-full whitespace-nowrap tabular-nums"><TableHeader className="sticky top-0 z-10"><TableRow>{['flow.time', 'flow.resource', 'flow.task', 'flow.operation', 'flow.net', 'flow.evidence'].map(key => <TableHead key={key}>{ui(key as 'flow.time')}</TableHead>)}</TableRow></TableHeader><TableBody>
          {shown.entries.map(entry => <TableRow key={entry.id}><TableCell>{entry.ts.slice(0, 19)}</TableCell><TableCell>{resourceLabel(entry.resource)}</TableCell><TableCell><Button type="button" variant="ghost" size="sm" onClick={() => {setTask(entry.task); setOffset(0)}}>{taskLabel(entry.task)}</Button></TableCell><TableCell>{entry.operation}</TableCell><TableCell className={entry.amount > 0 ? 'resource-income' : ''}>{entry.amount > 0 ? '+' : ''}{number(entry.amount)}</TableCell><TableCell><span className={`resource-evidence ${entry.evidence}`}>{evidence(entry.evidence)}</span></TableCell></TableRow>)}
        </TableBody></Table></div>
        {!shown.total && <p className="muted">{ui('flow.empty')}</p>}
        <div className="resource-pagination"><Button variant="outline" disabled={!offset || busy} onClick={() => setOffset(value => Math.max(0, value - 100))}>{ui('flow.prev')}</Button><span>{Math.floor(offset / 100) + 1} / {Math.max(1, Math.ceil(shown.total / 100))}</span><Button variant="outline" disabled={offset + 100 >= shown.total || busy} onClick={() => setOffset(value => value + 100)}>{ui('flow.next')}</Button></div>
      </section>
    </>}
  </div>
}
