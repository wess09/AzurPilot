import { Select } from '../components/FormControls'
import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  Award,
  Calculator,
  Cat,
  CheckCircle2,
  Clock,
  Coins,
  Cpu,
  Crosshair,
  Download,
  Flame,
  Fuel,
  Gem,
  Hourglass,
  Package,
  Percent,
  RefreshCw,
  RotateCw,
  ShoppingCart,
  Sparkles,
  Swords,
  Timer,
  TrendingUp,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import { api } from '../api/client'
import type { StatisticsReport } from '../api/types'
import type { Parameters } from '../api/generated'
import { useApp, useConnection } from '../app/context'
import { usesLegacyLayout } from '../app/theme'
import { ErrorBox, Loading, PageTitle } from '../components/ui'
import { SegmentedControl } from '../components/SegmentedControl'
import { RESEARCH_PREFIX, resolveIcon, StatisticsTable } from '../components/StatisticsTable'
import { downloadCsv } from '../components/statisticsData'
import type { UiKey } from '../i18n'
import { readStatisticsPrefs, updateStatisticsPrefs } from '../app/statisticsPrefs'

const metricIcons: Record<string, LucideIcon> = {
  '战斗次数': Swords,
  '出击轮数': RotateCw,
  '出击消耗': Flame,
  '明石遭遇': Cat,
  '明石遭遇率': Percent,
  '塞壬研究装置': Cpu,
  '装置获取率': Crosshair,
  '购买行动力': ShoppingCart,
  '平均每次购买': Calculator,
  '净行动力': Zap,
  '循环效率': TrendingUp,
  '完成委托': CheckCircle2,
  '钻石': Gem,
  '心智魔方': Package,
  '心智单元': Cpu,
  '石油': Fuel,
  '物资': Coins,
  '目标等级': Award,
  '预估经验效率': TrendingUp,
  '平均战斗时长': Clock,
  '平均每轮时长': Hourglass,
  '短猫平均战斗时长': Cat,
  '今日战斗': Swords,
  '今日经验': Sparkles,
  '今日运行': Timer,
}

const iconBase = import.meta.env.BASE_URL
const metricWebpIcons: Record<string, string> = {
  '完成委托': `${iconBase}honor_medal.webp`,
  '钻石': `${iconBase}diamond.webp`,
  '心智魔方': `${iconBase}cube.webp`,
  '心智单元': `${iconBase}core_data.webp`,
  '石油': `${iconBase}oil.webp`,
  '物资': `${iconBase}gold.webp`,
}

function getMetricWebp(label: string): string | undefined {
  if (metricWebpIcons[label]) return metricWebpIcons[label]
  for (const [key, src] of Object.entries(metricWebpIcons)) {
    if (label.includes(key) || key.includes(label)) return src
  }
  return undefined
}

function getMetricIcon(label: string): LucideIcon | undefined {
  if (metricIcons[label]) return metricIcons[label]
  for (const [key, icon] of Object.entries(metricIcons)) {
    if (label.includes(key) || key.includes(label)) return icon
  }
  return undefined
}

const StatisticsChart = lazy(() => import('../components/StatisticsChart').then(module => ({default: module.StatisticsChart})))
const categories: Record<Category, UiKey> = {resources: 'stats.category.resources', action: 'stats.category.action', opsi: 'stats.category.opsi', commission: 'stats.category.commission', ships: 'stats.category.ships', loot: 'stats.category.loot', research: 'stats.category.research'}
type Category = NonNullable<Parameters['statistics.report']['category']>

export function Statistics() {
  const {ui, theme, language} = useApp()
  const {instance = ''} = useParams()
  const legacy = usesLegacyLayout(theme)
  const initialPrefs = useRef(readStatisticsPrefs()).current
  const [category, setCategoryState] = useState<Category>(initialPrefs.category)
  const [days, setDaysState] = useState(initialPrefs.days)
  const [month, setMonth] = useState(() => {const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`})
  const [period, setPeriodState] = useState<'day' | 'week' | 'month'>(initialPrefs.period)
  // 科研视图：'1'~'9' = 各期（默认 9 期），'consumable' = 心智/物资。
  // 后者不分期——心智与物资各期混着出，只有彩装备与舰船图纸绑定期数。
  const [researchSeries, setResearchSeriesState] = useState(initialPrefs.researchSelect)
  const researchScope = researchSeries === 'consumable' ? researchSeries : 'series'
  // 科研的心智/物资视图不分期，看的是全部记录（后端 days 上限一年）；按期视图才用 days
  const requestDays = category === 'research' && researchScope !== 'series' ? 365 : days

  const setCategory = useCallback((next: Category) => {
    setCategoryState(next)
    updateStatisticsPrefs({category: next})
  }, [])
  const setDays = useCallback((next: number) => {
    setDaysState(next)
    updateStatisticsPrefs({days: next})
  }, [])
  const setPeriod = useCallback((next: 'day' | 'week' | 'month') => {
    setPeriodState(next)
    updateStatisticsPrefs({period: next})
  }, [])
  const setResearchSeries = useCallback((next: string) => {
    setResearchSeriesState(next)
    updateStatisticsPrefs({researchSelect: next})
  }, [])

  const [revision, setRevision] = useState(0)
  const [data, setData] = useState<StatisticsReport>()
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  /* 放大视图由页面工具栏控制：紧凑主题把「放大查看」并进工具栏，面板内不再重复标题行。 */
  const [expanded, setExpanded] = useState(false)
  const toggleExpanded = useCallback(() => setExpanded(value => !value), [])
  // 分段控件放不下时会被压缩并横向滚动（.monitor-segmented 带 overflow-x: auto），
  // 这里按可用宽度精确判断、一旦放不下就换成下拉；右侧控件宽度随分类变化，不能用固定断点。
  const [compact, setCompact] = useState(false)
  const toolbarRow = useRef<HTMLDivElement>(null)
  const toolbarRight = useRef<HTMLDivElement>(null)
  const naturalWidth = useRef(0)
  const connection = useConnection()
  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    setData(undefined); setError('')
    void api.request('statistics.report', {instance, category, days: requestDays, month, period, series: researchScope === 'series' ? Number(researchSeries) : 0, scope: researchScope}).then(value => {if (active) setData(value)}).catch(error => {if (active) setError(error.message)})
    return () => {active = false}
  }, [instance, category, requestDays, month, period, researchSeries, connection, revision])

  // 静默更新：后端数据更新推送到前端时平滑更新图表与指标，避免 Loading 闪烁
  const silentRefresh = useCallback(() => {
    if (connection !== 'ready') return
    void api.request('statistics.report', {instance, category, days: requestDays, month, period, series: researchScope === 'series' ? Number(researchSeries) : 0, scope: researchScope})
      .then(value => {
        setData(value)
      })
      .catch(() => {
        // 静默更新失败时不影响当前已展示视图
      })
  }, [connection, instance, category, requestDays, month, period, researchSeries])

  useEffect(() => {
    if (connection !== 'ready') return
    let timer: ReturnType<typeof setTimeout> | undefined
    const triggerUpdate = () => {
      clearTimeout(timer)
      timer = setTimeout(silentRefresh, 300)
    }

    return api.onEvent(event => {
      if (event.topic === 'statistics') {
        const payload = event.data as {instance?: string} | undefined
        if (!payload?.instance || payload.instance === instance) {
          triggerUpdate()
        }
      } else if (event.topic === 'overview') {
        const payload = event.data as {instance?: string} | undefined
        if (payload?.instance === instance) {
          triggerUpdate()
        }
      }
    })
  }, [connection, instance, silentRefresh])
  // 分段控件可见时记录它的自然宽度；隐藏后 clientWidth 为 0，沿用上次的值避免来回抖动。
  // 除工具栏与右侧控件外还要观察分段控件自身：切换语言会改变标签文字宽度，
  // 此时工具栏宽度没变，只有控件自己的尺寸变了。
  useLayoutEffect(() => {
    const row = toolbarRow.current
    const right = toolbarRight.current
    if (!row || !right) return
    const control = row.querySelector<HTMLElement>('.statistics-category-control')
    const measure = () => {
      // flex: 0 0 auto + width: max-content 下 offsetWidth 就是内容自然宽度
      if (control && control.clientWidth > 0) naturalWidth.current = control.offsetWidth
      if (!naturalWidth.current) return
      setCompact(row.clientWidth - right.offsetWidth - 12 < naturalWidth.current)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(row)
    observer.observe(right)
    if (control) observer.observe(control)
    return () => observer.disconnect()
  }, [language])

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
  // 只有紧凑主题把分类、时间范围与操作并成一行并置顶，其余主题维持原来的两行结构。
  const condensed = theme === 'extreme'
  /* 没有图表的分类（只有汇总卡片与明细表）不放「放大查看」。 */
  const hasChart = Boolean(data?.series.length)
  /* 控件名不再常驻在工具栏上：紧凑主题把文字收进 hover/聚焦提示（data-tip），
     横向空间让给数据；其它主题仍按原样显示标签文字。 */
  const rangeControls = <>
    {category === 'resources' && <label className="statistics-inline-control" data-tip={ui('stats.range')}><span className="statistics-inline-label">{ui('stats.range')}</span><Select aria-label={ui('stats.days')} value={days} onChange={event => setDays(Number(event.target.value))}>{[1, 7, 30, 90, 365].map(value => <option value={value} key={value}>{ui('stats.recentDays', {days: value})}</option>)}</Select></label>}
    {/* 月份输入框本身就显示「2026年09月」，标签只在提示里出现 */}
    {(['action', 'opsi', 'commission'].includes(category!) || (category === 'research' && researchScope === 'series')) && <label className="statistics-inline-control" data-tip={ui('stats.month')}><input aria-label={ui('stats.month')} type="month" min="2020-01" max="9998-12" value={month} disabled={(category === 'commission' || category === 'research') && period !== 'month'} onChange={event => {if (event.target.value) setMonth(event.target.value)}}/></label>}
    {category === 'research' && <label className="statistics-inline-control" data-tip={ui('stats.researchSeries')}><span className="statistics-inline-label">{ui('stats.researchSeries')}</span><Select aria-label={ui('stats.researchSeries')} value={researchSeries} onChange={event => setResearchSeries(String(event.target.value))}>{[1, 2, 3, 4, 5, 6, 7, 8, 9].map(value => <option value={String(value)} key={value}>{ui('stats.seriesN', {n: value})}</option>)}<option value="consumable">{ui('stats.consumableScope')}</option></Select></label>}
    {category === 'commission' && <label className="statistics-inline-control" data-tip={ui('stats.period')}><span className="statistics-inline-label">{ui('stats.period')}</span><Select aria-label={ui('stats.commissionPeriod')} value={period} onChange={event => setPeriod(event.target.value as typeof period)}><option value="day">{ui('stats.today')}</option><option value="week">{ui('stats.thisWeek')}</option><option value="month">{ui('stats.selectedMonth')}</option></Select></label>}
    {category === 'research' && researchScope === 'series' && <label className="statistics-inline-control" data-tip={ui('stats.period')}><span className="statistics-inline-label">{ui('stats.period')}</span><Select aria-label={ui('stats.period')} value={period} onChange={event => setPeriod(event.target.value as typeof period)}><option value="day">{ui('stats.today')}</option><option value="week">{ui('stats.thisWeek')}</option><option value="month">{ui('stats.selectedMonth')}</option></Select></label>}
  </>
  const hints = <>
    {category === 'ships' && <span>{ui('stats.shipHint')}</span>}
    {category === 'loot' && <span>{ui('stats.lootHint')}</span>}
  </>
  const dataView = error ? <ErrorBox message={error} retry={() => setRevision(value => value + 1)}/> : !data ? <Loading/> : <div className="statistics-sections">{!!data.metrics.length && <section className="panel summary-metrics-panel"><div className="stat-metrics summary-metrics">{data.metrics.map(item => {
    const research = item.icon?.startsWith(RESEARCH_PREFIX) ? resolveIcon(item.icon) : undefined
    const webp = research?.src ?? getMetricWebp(item.label)
    const Icon = !webp ? getMetricIcon(item.label) : undefined
    return <div key={item.label} className="summary-metric-card">
      <div className="summary-metric-head">
        <span className="summary-metric-label">{item.label}</span>
        {webp ? (
          <span className="summary-metric-icon summary-metric-icon-webp" aria-hidden="true">
            <img src={webp} alt="" width={48} height={48} draggable={false}/>
          </span>
        ) : Icon ? (
          <span className="summary-metric-icon" aria-hidden="true">
            <Icon size={18} strokeWidth={1.8}/>
          </span>
        ) : null}
      </div>
      <strong>{item.value == null ? '—' : item.value.toLocaleString(undefined, {maximumFractionDigits: 2})}<small>{item.unit}</small></strong>
    </div>
  })}</div></section>}{!!data.series.length && <Suspense fallback={<Loading/>}><StatisticsChart key={category} category={category} series={data.series} tables={condensed ? data.tables : []} heading={!condensed} expanded={expanded} onToggleExpanded={toggleExpanded} title={ui(categories[category])}/></Suspense>}{!condensed && data.tables.map(table => <section className="panel" key={table.title}><StatisticsTable data={table}/></section>)}</div>

  const content = <>
    {condensed
      ? <div className={`statistics-toolbar-row${compact ? ' is-compact' : ''}`} ref={toolbarRow}>
          <SegmentedControl className="statistics-category-control" label={ui('stats.categoryLabel')} value={category} onChange={setCategory} options={Object.entries(categories).map(([value, label]) => ({value: value as Category, label: ui(label)}))}/>
          {/* 放不下时改用单按钮下拉；指针移入或键盘聚焦即展开，见 Select 的 openOnFocus */}
          <Select openOnFocus className="statistics-category-select" aria-label={ui('stats.categoryLabel')} value={category} onChange={event => setCategory(event.target.value as Category)}>
            {Object.entries(categories).map(([value, label]) => <option value={value} key={value}>{ui(label)}</option>)}
          </Select>
          <div className="statistics-toolbar-right" ref={toolbarRight}>{hasChart && <button className="text-button" onClick={toggleExpanded}>{expanded ? ui('stats.collapseChart') : ui('stats.expandChart')}</button>}{rangeControls}<div className="statistics-actions">{actions}</div></div>
        </div>
      : <>
          <div className="statistics-toolbar-row">
            <SegmentedControl className="statistics-category-control" label={ui('stats.categoryLabel')} value={category} onChange={setCategory} options={Object.entries(categories).map(([value, label]) => ({value: value as Category, label: ui(label)}))}/>
            {legacy && <div className="statistics-actions">{actions}</div>}
          </div>
          <div className="statistics-controls period-controls"><strong>{ui(categories[category!])}</strong>{rangeControls}{hints}</div>
        </>}
    {condensed && (category === 'ships' || category === 'loot') && <div className="statistics-controls period-controls">{hints}</div>}
    {dataView}
  </>

  // 旧版版式：整页只放统计内容（不放调度器与任务计划），页名由顶栏居中显示。
  if (legacy) return <>
    <div className="statistics-legacy">
      <h1 className="legacy-sr-title">{ui('nav.statistics')}</h1>
      {content}
    </div>
  </>

  // 紧凑主题下页名与面包屑重复，省略标题行只留无障碍标题；其余主题保持原样。
  return condensed
    ? <><h1 className="sr-title">{ui('nav.statistics')}</h1>{content}</>
    : <><PageTitle title={ui('nav.statistics')} actions={actions}/>{content}</>
}
