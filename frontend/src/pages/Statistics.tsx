import { Select } from '../components/FormControls'
import { lazy, Suspense, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Download, RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import type { StatisticsReport } from '../api/types'
import type { Parameters } from '../api/generated'
import { useApp, useConnection } from '../app/context'
import { usesLegacyLayout } from '../app/theme'
import { ErrorBox, Loading, PageTitle } from '../components/ui'
import { SegmentedControl } from '../components/SegmentedControl'
import { StatisticsTable } from '../components/StatisticsTable'
import { LegacyRail } from '../components/LegacyRail'
import { useInstanceOverview } from '../components/useInstanceOverview'
import { downloadCsv } from '../components/statisticsData'
import type { UiKey } from '../i18n'

const StatisticsChart = lazy(() => import('../components/StatisticsChart').then(module => ({default: module.StatisticsChart})))
const categories: Record<Category, UiKey> = {resources: 'stats.category.resources', action: 'stats.category.action', opsi: 'stats.category.opsi', commission: 'stats.category.commission', ships: 'stats.category.ships', loot: 'stats.category.loot'}
type Category = NonNullable<Parameters['statistics.report']['category']>

export function Statistics() {
  const {ui, theme} = useApp()
  const {instance = ''} = useParams()
  // 旧版主题把左侧那一列让给调度器与任务计划，只有这种版式才需要总览数据。
  const legacy = usesLegacyLayout(theme)
  const [railData, setRailData] = useInstanceOverview(instance, legacy)
  const [category, setCategory] = useState<Category>('resources')
  const [days, setDays] = useState(7)
  const [month, setMonth] = useState(() => {const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`})
  const [period, setPeriod] = useState<'day' | 'week' | 'month'>('month')
  const [revision, setRevision] = useState(0)
  const [data, setData] = useState<StatisticsReport>()
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const connection = useConnection()
  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    setData(undefined); setError('')
    void api.request('statistics.report', {instance, category, days, month, period}).then(value => {if (active) setData(value)}).catch(error => {if (active) setError(error.message)})
    return () => {active = false}
  }, [instance, category, days, month, period, connection, revision])
  async function refresh() {
    setRefreshing(true)
    try {
      if (category === 'loot') await api.request('statistics.refreshLoot', {instance})
      setRevision(value => value + 1)
    } catch (error) {setError((error as Error).message)} finally {setRefreshing(false)}
  }
  function download() {
    if (!data) return
    downloadCsv(`${instance}-${ui(categories[category!])}-${data.month}`, [
      [ui('stats.metric'), ui('stats.value'), ui('stats.unit')], ...data.metrics.map(item => [item.label, item.value, item.unit]),
      ...data.tables.flatMap(table => [[table.title], table.columns, ...table.rows, []]),
      ...data.series.flatMap(series => [[series.label], [ui('stats.time'), ui('stats.value'), ui('stats.source')], ...series.points.map(point => [point.time, point.value, point.source ?? '']), []]),
      ...(data.notes.length ? [[ui('stats.notes')], ...data.notes.map(note => [note])] : []),
    ])
  }
  const actions = <><button className="button secondary" disabled={connection !== 'ready' || refreshing} onClick={refresh}><RefreshCw size={15}/>{refreshing ? ui('stats.refreshing') : ui('stats.refresh')}</button><button className="button secondary" disabled={!data} onClick={download}><Download size={15}/>{ui('stats.exportCategory')}</button></>
  const content = <>
    <div className="statistics-toolbar-row">
      <SegmentedControl className="statistics-category-control" label={ui('stats.categoryLabel')} value={category} onChange={setCategory} options={Object.entries(categories).map(([value, label]) => ({value: value as Category, label: ui(label)}))}/>
      {legacy && <div className="statistics-actions">{actions}</div>}
    </div>
    <div className="statistics-controls period-controls"><strong>{ui(categories[category!])}</strong>{category === 'resources' ? <label>{ui('stats.range')}<Select aria-label={ui('stats.days')} value={days} onChange={event => setDays(Number(event.target.value))}>{[1, 7, 30, 90, 365].map(value => <option value={value} key={value}>{ui('stats.recentDays', {days: value})}</option>)}</Select></label> : ['action', 'opsi', 'commission'].includes(category!) && <label>{ui('stats.month')}<input aria-label={ui('stats.month')} type="month" min="2020-01" max="9998-12" value={month} disabled={category === 'commission' && period !== 'month'} onChange={event => {if (event.target.value) setMonth(event.target.value)}}/></label>}{category === 'commission' && <label>{ui('stats.period')}<Select aria-label={ui('stats.commissionPeriod')} value={period} onChange={event => setPeriod(event.target.value as typeof period)}><option value="day">{ui('stats.today')}</option><option value="week">{ui('stats.thisWeek')}</option><option value="month">{ui('stats.selectedMonth')}</option></Select></label>}{category === 'ships' && <span>{ui('stats.shipHint')}</span>}{category === 'loot' && <span>{ui('stats.lootHint')}</span>}</div>
    {error ? <ErrorBox message={error} retry={() => setRevision(value => value + 1)}/> : !data ? <Loading/> : <div className="statistics-sections">{!!data.metrics.length && <div className="stat-metrics summary-metrics">{data.metrics.map(item => <section key={item.label}><span>{item.label}</span><strong>{item.value == null ? '—' : item.value.toLocaleString(undefined, {maximumFractionDigits: 2})}<small>{item.unit}</small></strong></section>)}</div>}{!!data.series.length && <Suspense fallback={<Loading/>}><StatisticsChart key={category} series={data.series}/></Suspense>}{data.tables.map(table => <section className="panel" key={table.title}><StatisticsTable data={table}/></section>)}</div>}
  </>

  // 旧版版式：左列调度器与任务计划，右列统计内容；页名由顶栏居中显示。
  if (legacy) return <>
    <div className="instance-page-grid">
      <h1 className="legacy-sr-title">{ui('nav.statistics')}</h1>
      <LegacyRail instance={instance} data={railData} onData={setRailData}/>
      <div className="instance-page-main">{content}</div>
    </div>
  </>

  return <><PageTitle title={ui('nav.statistics')} actions={actions}/>{content}</>
}
