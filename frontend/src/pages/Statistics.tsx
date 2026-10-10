/**
 * @fileoverview 数据统计与图表分析页面。
 */

import {NumberDraftInput, Select} from '../components/FormControls'
import { Fragment, lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'
import { getSelectedKeysForCategory, getStatisticsPrefs, getStatisticsPrefsVersion, subscribeStatisticsPrefs } from '../app/statisticsPrefs'
import { useParams, useSearchParams } from 'react-router-dom'
import {
  Award,
  Calculator,
  Cat,
  CheckCircle2,
  ChevronDown,
  Clock,
  Coins,
  Cpu,
  Crosshair,
  Download,
  ArrowDown,
  ArrowUp,
  Flame,
  Fuel,
  Eye,
  EyeOff,
  Gem,
  GripVertical,
  Plus,
  Hourglass,
  Package,
  Play,
  Paintbrush,
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
import { editor } from '../config/editors'
import type { StatTable, StatisticsReport } from '../api/types'
import type { Parameters } from '../api/generated'
import { useApp, useConnection } from '../app/context'
import { usesLegacyLayout } from '../app/theme'
import { ActionGroup, ErrorBox, Loading, PageTitle } from '../components/ui'
import { SegmentedControl } from '../components/SegmentedControl'
import { resolveIcon, resourceIcons, StatisticsTable, TEMPLATE_PREFIXES } from '../components/StatisticsTable'
import { CategorySection } from '../components/CategorySection'
import { PageChainSlots } from '../components/PageChainSlots'
import { StatisticsEditConsole } from '../components/StatisticsEditConsole'
import { buildSeriesView, downloadCsv } from '../components/statisticsData'
import type { UiKey } from '../i18n'
import { readStatisticsPrefs, updateStatisticsPrefs } from '../app/statisticsPrefs'
import {applySlots, cardKey, cardSpace, DEFAULT_TABLE_ROWS, defaultStatisticsLayout, foldCard, hasStatisticsLayout, hideCard, pageNeedsSeries, isCardFolded, isCardHidden, isChartCompact, isLinked, isMetricsTable, isPageEnabled, isPickerHidden, isStackedRise, linkChains, movePageBeside, orderCards, orderPages, placeCard, readChains, readStatisticsEditMode, readStatisticsLayout, rechain, resetStatisticsLayout, setChartCompact, setMetricsTable, setPageEnabled, setPickerHidden, setStackedRise, setTableDisplay, showCard, splitChains, tableDisplay, toggleSeriesFilter, unfoldCard, writeStatisticsEditMode, writeStatisticsLayout} from '../app/statisticsLayout'
import type {StatisticsLayout} from '../app/statisticsLayout'

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
  '心智单元': `${iconBase}cognitive_chips.webp`,
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
const ResourceManagement = lazy(() => import('./ResourceManagement').then(module => ({default: module.ResourceManagement})))
const categories: Record<Category, UiKey> = {resources: 'stats.category.resources', action: 'stats.category.action', opsi: 'stats.category.opsi', commission: 'stats.category.commission', ships: 'stats.category.ships', loot: 'stats.category.loot', research: 'stats.category.research', storage: 'stats.category.storage'}
type Category = NonNullable<Parameters['statistics.report']['category']>
type StatisticsView = Category | 'management'

/* 页面显示开关按固定顺序排列，与排序后的页面顺序无关。 */
const fixedPageOrder = defaultStatisticsLayout().pages.flat()

/* 收获指标图标：自定义图标优先，其次本地 webp，再次内置图标。 */
function metricIcon(item: {label: string; icon?: string}) {
  const custom = item.icon ? resolveIcon(item.icon) : undefined
  const webp = custom?.src ?? getMetricWebp(item.label)
  const Icon = !webp ? getMetricIcon(item.label) : undefined
  if (webp) return <span className="summary-metric-icon summary-metric-icon-webp" aria-hidden="true"><img src={webp} alt="" width={48} height={48} draggable={false}/></span>
  if (Icon) return <span className="summary-metric-icon" aria-hidden="true"><Icon size={18} strokeWidth={1.8}/></span>
  return null
}
/** 这张表有没有图标可出：资源名认列名；科研与大世界掉落的图标写在单元格值里（research: / opsi: 前缀），
   列名看不出来，两者都要查。 */
function hasTableIcons(table: StatTable): boolean {
  if (table.columns.some(column => column in resourceIcons || TEMPLATE_PREFIXES.some(prefix => column.startsWith(prefix)))) return true
  return table.rows.some(row => row.some(value => typeof value === 'string' && TEMPLATE_PREFIXES.some(prefix => value.startsWith(prefix))))
}

/** 收获的表格模式：把指标摊成一张单行表，复用明细表那套表格。
    标题由调用方带前缀传入（如「大世界总结·收获」）。 */
function metricsTableData(title: string, metrics: StatisticsReport['metrics']): StatTable {
  return {title, columns: metrics.map(item => item.label), rows: [metrics.map(item => item.value)]}
}
export function Statistics() {
  const {ui, theme, language, notify} = useApp()
  const {instance = ''} = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const management = searchParams.get('view') === 'management'
  const legacy = usesLegacyLayout(theme)
  const initialPrefs = useRef(readStatisticsPrefs()).current
  const [category, setCategoryState] = useState<Category>(initialPrefs.category)
  const [days, setDaysState] = useState(initialPrefs.days)
  const [month, setMonth] = useState(() => {const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`})
  const [period, setPeriodState] = useState<'day' | 'week' | 'month'>(initialPrefs.period)
  // 科研视图：'1'~'9' = 各期（默认 9 期），'consumable' = 心智/物资。
  // 后者不分期：心智与物资各期混着出，只有彩装备与舰船图纸绑定期数。
  const [researchSeries, setResearchSeriesState] = useState(initialPrefs.researchSelect)
  // 大世界掉落视图：'' = 全部大世界任务，其余是任务标识（选项由后端 taskOptions 给出）
  const [lootTask, setLootTaskState] = useState(initialPrefs.lootTask)
  const [zeroBase, setZeroBaseState] = useState(initialPrefs.chartZeroBase)

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
  const setLootTask = useCallback((next: string) => {
    setLootTaskState(next)
    updateStatisticsPrefs({lootTask: next})
  }, [])
  const setZeroBase = useCallback((next: boolean) => {
    setZeroBaseState(next)
    updateStatisticsPrefs({chartZeroBase: next})
  }, [])

  const [revision, setRevision] = useState(0)
  const [data, setData] = useState<StatisticsReport>()
  const [refreshing, setRefreshing] = useState(false)
  const [startingStorage, setStartingStorage] = useState(false)
  const [storageError, setStorageError] = useState('')
  const [editMode, setEditMode] = useState(readStatisticsEditMode)
  const [customized, setCustomized] = useState(hasStatisticsLayout)
  const [layout, setLayout] = useState(readStatisticsLayout)
  /* 原始记录表的内容由图表计算，这里只给它一张卡片的位置。 */
  useSyncExternalStore(subscribeStatisticsPrefs, getStatisticsPrefsVersion, getStatisticsPrefsVersion)
  const prefs = getStatisticsPrefs()

  /* 原始记录卡自己算同一份数据：筛选与图表一致，两边读同一份偏好。 */
  const rawTableOf = (page: Category, report: StatisticsReport | undefined) => {
    if (!report) return null
    const view = buildSeriesView(report.series, {selectedKeys: getSelectedKeysForCategory(page, report.series), mode: prefs.chartMode, bucket: prefs.bucket, from: prefs.rangeFrom, to: prefs.rangeTo})
    return {
      title: view.isSingle ? ui('stats.rawTitle', {label: view.selectedSeries[0].label}) : ui('stats.multiMetrics'),
      columns: view.isSingle ? [ui('stats.time'), ui('stats.value'), ui('stats.source')] : [ui('stats.time'), ...view.selectedSeries.map(item => item.label), ui('stats.source')],
      rows: view.mergedRows,
      defaultSort: {index: 0, descending: true},
    }
  }
  const [draggingKey, setDraggingKey] = useState<string | null>(null)
  const [dropTarget, setDropTarget] = useState<{key: string, after: boolean} | null>(null)

  const toggleEditMode = () => {
    const next = !editMode
    writeStatisticsEditMode(next)
    setEditMode(next)
    notify(ui(next ? 'stats.editEntered' : 'stats.editExited'))
  }
  const resetLayout = () => {
    resetStatisticsLayout()
    setLayout(readStatisticsLayout())
    setCustomized(false)
    notify(ui('stats.editResetDone'))
  }
  const applyLayout = (next: StatisticsLayout) => {
    writeStatisticsLayout(next)
    setLayout(next)
    setCustomized(true)
  }
  /* 展开状态按分区记录：组合页里每个分区各有一张图卡，放大只作用于被点的那张。
     紧凑主题把「放大查看」并进工具栏，面板内不再重复标题行。 */
  const [expandedChart, setExpandedChart] = useState<string | null>(null)
  const toggleExpanded = useCallback((page: string) => setExpandedChart(current => current === page ? null : page), [])
  // 分段控件放不下时会被压缩并横向滚动（.monitor-segmented 带 overflow-x: auto），
  // 这里按可用宽度精确判断、一旦放不下就换成下拉；右侧控件宽度随分类变化，不能用固定断点。
  const [compact, setCompact] = useState(false)
  const toolbarRow = useRef<HTMLDivElement>(null)
  const toolbarRight = useRef<HTMLDivElement>(null)
  const naturalWidth = useRef(0)
  const connection = useConnection()
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
    } catch {
      /* 刷新失败时保持当前视图：各分节自身的取数错误会呈现。 */
    } finally {setRefreshing(false)}
  }
  async function runStorageStatistics() {
    setStartingStorage(true)
    setStorageError('')
    try {
      await editor(`config:${instance}`).settled()
      await api.request('tasks.run', {instance, task: 'StorageStatistics'})
      notify(ui('stats.storageStarted'))
    } catch (error) {
      setStorageError((error as Error).message)
    } finally {setStartingStorage(false)}
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
  const actions = <>{category === 'storage' && <button className="button secondary" disabled={connection !== 'ready' || startingStorage} onClick={runStorageStatistics}><Play size={15}/>{ui('stats.runStorage')}</button>}<button className="button secondary" disabled={connection !== 'ready' || refreshing} onClick={refresh}><RefreshCw size={15}/>{refreshing ? ui('stats.refreshing') : ui('stats.refresh')}</button><button className="button secondary" disabled={!data} onClick={download}><Download size={15}/>{ui('stats.exportCategory')}</button><button className="button secondary statistics-edit-toggle" aria-pressed={editMode} onClick={toggleEditMode}><Paintbrush size={15}/>{ui('stats.editMode')}</button></>
  // 只有紧凑主题把分类、时间范围与操作并成一行并置顶，其余主题维持原来的两行结构。
  const condensed = theme === 'extreme'
  /* 没有图表的分类（只有汇总卡片与明细表）不放「放大查看」。 */
  const hasChart = Boolean(data?.series.length)
  /* 控件名不再常驻在工具栏上：紧凑主题把文字收进 hover/聚焦提示（data-tip），
     横向空间让给数据；其它主题仍按原样显示标签文字。 */
  const rangeControls = <>
    {(category === 'resources' || category === 'storage') && period === 'day' && <label className="statistics-inline-control" data-tip={ui('stats.range')}><span className="statistics-inline-label">{ui('stats.range')}</span><Select aria-label={ui('stats.days')} value={days} onChange={event => setDays(Number(event.target.value))}>{[1, 7, 30, 90, 365].map(value => <option value={value} key={value}>{ui('stats.recentDays', {days: value})}</option>)}</Select></label>}
    {/* 月份输入框本身就显示「2026年09月」，标签只在提示里出现 */}
    {(['action', 'opsi', 'commission', 'loot', 'resources', 'storage'].includes(category!) || category === 'research') && <label className="statistics-inline-control" data-tip={ui('stats.month')}><input aria-label={ui('stats.month')} type="month" min="2020-01" max="9998-12" value={month} disabled={(['commission', 'research', 'loot', 'resources', 'storage'].includes(category!)) && period !== 'month'} onChange={event => {if (event.target.value) setMonth(event.target.value)}}/></label>}
    {category === 'research' && <label className="statistics-inline-control" data-tip={ui('stats.researchSeries')}><span className="statistics-inline-label">{ui('stats.researchSeries')}</span><Select aria-label={ui('stats.researchSeries')} value={researchSeries} onChange={event => setResearchSeries(String(event.target.value))}>{[1, 2, 3, 4, 5, 6, 7, 8, 9].map(value => <option value={String(value)} key={value}>{ui('stats.seriesN', {n: value})}</option>)}<option value="consumable">{ui('stats.consumableScope')}</option></Select></label>}
    {(category === 'resources' || category === 'storage') && <label className="statistics-inline-control" data-tip={ui('stats.period')}><span className="statistics-inline-label">{ui('stats.period')}</span><Select aria-label={ui('stats.period')} value={period} onChange={event => setPeriod(event.target.value as typeof period)}><option value="day">{ui('stats.recentDays', {days})}</option><option value="week">{ui('stats.thisWeek')}</option><option value="month">{ui('stats.selectedMonth')}</option></Select></label>}
    {category === 'commission' && <label className="statistics-inline-control" data-tip={ui('stats.period')}><span className="statistics-inline-label">{ui('stats.period')}</span><Select aria-label={ui('stats.commissionPeriod')} value={period} onChange={event => setPeriod(event.target.value as typeof period)}><option value="day">{ui('stats.today')}</option><option value="week">{ui('stats.thisWeek')}</option><option value="month">{ui('stats.selectedMonth')}</option></Select></label>}
    {category === 'research' && <label className="statistics-inline-control" data-tip={ui('stats.period')}><span className="statistics-inline-label">{ui('stats.period')}</span><Select aria-label={ui('stats.period')} value={period} onChange={event => setPeriod(event.target.value as typeof period)}><option value="day">{ui('stats.today')}</option><option value="week">{ui('stats.thisWeek')}</option><option value="month">{ui('stats.selectedMonth')}</option></Select></label>}
    {/* 大世界掉落：任务筛选的选项来自后端（含当前窗口内没记录的任务），值就是任务标识 */}
    {category === 'loot' && <label className="statistics-inline-control" data-tip={ui('stats.lootTask')}><span className="statistics-inline-label">{ui('stats.lootTask')}</span><Select aria-label={ui('stats.lootTask')} value={lootTask} onChange={event => setLootTask(String(event.target.value))}><option value="">{ui('stats.lootTaskAll')}</option>{(data?.taskOptions ?? []).map(item => <option value={item.key} key={item.key}>{item.count ? `${item.label}（${item.count}）` : item.label}</option>)}</Select></label>}
    {category === 'loot' && <label className="statistics-inline-control" data-tip={ui('stats.period')}><span className="statistics-inline-label">{ui('stats.period')}</span><Select aria-label={ui('stats.period')} value={period} onChange={event => setPeriod(event.target.value as typeof period)}><option value="day">{ui('stats.today')}</option><option value="week">{ui('stats.thisWeek')}</option><option value="month">{ui('stats.selectedMonth')}</option></Select></label>}
  </>
  const hints = <>
    {category === 'ships' && <span>{ui('stats.shipHint')}</span>}
    {category === 'loot' && <span>{ui('stats.lootHint')}</span>}
  </>
  /* 页面级卡片视图：键、组合链、顺序与渲染序列都由该页自身的数据决定。 */
  /* 单页的卡片键与默认连接：组合链的整链键表由链上各页拼出。 */
  const pageCards = (page: Category, report: StatisticsReport | undefined) => {
    const tableKeys = report ? report.tables.map(table => cardKey(page, `table:${table.title}`)) : []
    const metricsKey = cardKey(page, 'metrics')
    const chartKey = cardKey(page, 'chart')
    const plotKey = cardKey(page, 'chart:plot')
    const rawKey = cardKey(page, 'raw')
    const cardKeys = report ? [...(report.metrics.length ? [metricsKey] : []), ...(report.series.length ? [chartKey, rawKey] : []), ...tableKeys] : []
    /* 默认连成一条，还原原版行为：图表与其原始记录表始终相连，紧凑外壳下其余表格也相连。 */
    const defaultChains = report?.series.length ? [[chartKey, rawKey, ...(condensed ? tableKeys : [])]] : []
    return {metricsKey, chartKey, plotKey, rawKey, tableKeys, cardKeys, defaultChains}
  }

  /* 单页视图把全部启用页面当成一条整链，跨页拖动与跨页连接才有结算依据。 */
  const spaceOf = (page: Category) => layout.singleView ? orderPages(layout).filter(id => isPageEnabled(layout, id)) : layout.pages.find(chain => chain.includes(page)) ?? [page]
  const spaceKeysOf = (page: Category) => spaceOf(page).flatMap(item => pageCards(item, chainData[item]).cardKeys)
  /* 整链中当前显示中的卡片键，按整链顺序：拆分与插入按它判定相邻关系，隐藏卡不参与。 */
  const spaceVisibleOf = (page: Category) => orderCards(layout, page, spaceKeysOf(page)).filter(key => !isCardHidden(layout, key))
  /* 连接或拆分涉及的两张卡必然属于新链，键表必须包含它们，否则会被当成未知键丢掉。 */
  const keyListFor = (page: Category, ...keys: string[]) => [...new Set([...spaceVisibleOf(page), ...keys])]

  const pageView = (page: Category, report: StatisticsReport | undefined) => {
    const {metricsKey, chartKey, plotKey, rawKey, tableKeys, cardKeys} = pageCards(page, report)
    const cardClass = (key: string) => `stat-card${isCardFolded(layout, key) ? ' is-folded' : ''}`
    const foldControl = (key: string, place?: 'corner' | 'center', foldLabel: UiKey = 'stats.foldCard', unfoldLabel: UiKey = 'stats.unfoldCard') => {
      const folded = isCardFolded(layout, key)
      return <button className={`text-button stat-card-fold${place ? ` is-${place}` : ''}`} aria-expanded={!folded} aria-label={ui(folded ? unfoldLabel : foldLabel)} onClick={() => applyLayout(folded ? unfoldCard(layout, key) : foldCard(layout, key))}><ChevronDown size={15}/></button>
    }
    const defaultChains = spaceOf(page).flatMap(item => pageCards(item, chainData[item]).defaultChains)
    const chains = report ? readChains(layout, page, defaultChains) : []
    /* 整链顺序：跨页组合后邻卡可能在另一页，接缝层按它取后续的隐藏卡占位条；可见卡序供接缝判断下一张。 */
    const spaceOrder = report ? orderCards(layout, page, spaceKeysOf(page)) : []

    return {cardClass, foldControl, metricsKey, chartKey, plotKey, rawKey, tableKeys, cardKeys, chains, spaceOrder, visibleKeys: spaceOrder.filter(key => cardKeys.includes(key) && !isCardHidden(layout, key))}
  }

  /* 卡片空间视图：一个空间（组合页或单页视图）渲染成一段，链与顺序在空间全量上算，
     跨页的链因此落进同一个容器。 */
  const spaceView = (space: Category[]) => {
    const keys = space.flatMap(page => pageCards(page, chainData[page]).cardKeys)
    const chains = readChains(layout, space[0], space.flatMap(page => pageCards(page, chainData[page]).defaultChains))
    const ordered = orderCards(layout, space[0], keys)
    const visible = ordered.filter(key => !isCardHidden(layout, key))
    const runs: {keys: string[]}[] = []
    let lastShown: string | undefined
    for (let index = 0; index < ordered.length; index += 1) {
      const key = ordered[index]
      const hidden = isCardHidden(layout, key)
      if (hidden && !editMode) continue
      const current = runs[runs.length - 1]
      /* 隐藏卡夹在同一链的两张卡之间时留在链内：两侧卡片保持一体，只由占位条标出位置。 */
      const linked = hidden ? ordered.slice(index + 1).find(item => !isCardHidden(layout, item)) : key
      if (current && lastShown && linked && isLinked(chains, lastShown, linked)) current.keys.push(key)
      else runs.push({keys: [key]})
      if (!hidden) lastShown = key
    }
    return {chains, ordered, visible, runs}
  }

  type PageView = ReturnType<typeof pageView>
  const [chainData, setChainData] = useState<Partial<Record<Category, StatisticsReport>>>({})
  const [chainError, setChainError] = useState<Partial<Record<Category, string>>>({})
  /* 分节上报数据：同一份数据复用同一对象。 */
  const reportOf = useCallback((page: Category, report: StatisticsReport | undefined, error = '') => {
    setChainData(prev => (prev[page] === report ? prev : {...prev, [page]: report}))
    setChainError(prev => (prev[page] === error ? prev : {...prev, [page]: error}))
    if (page === category) setData(report)
  }, [category])
  const activeView = pageView(category!, data)
  const applyChains = (page: Category, view: PageView, next: StatisticsLayout, moved?: string) => applyLayout({...next, cards: {...next.cards, [cardSpace(layout, page)]: rechain(view.chains, orderCards(next, page, spaceKeysOf(page)).filter(item => !isCardHidden(next, item)), moved)}})
  const pageIds = orderPages(layout)
  const singleView = layout.singleView
  const singleViewToggle = editMode ? <button type="button" className="statistics-single-view" aria-pressed={singleView} aria-label={ui('stats.mergePages')} title={ui('stats.mergePages')} onClick={() => applyLayout({...layout, singleView: !singleView})}>{ui('stats.mergePages')}</button> : undefined
  const pageEntries = pageIds.map(id => [id, categories[id]] as [Category, UiKey])
  /* 非编辑模式一条链只留首个在前的页面；编辑模式七个页面都在，便于拆开组合。 */
  const chainOf = (page: Category) => layout.pages.find(chain => chain.includes(page)) ?? [page]
  const visiblePageEntries = pageEntries.filter(([id]) => (editMode || isPageEnabled(layout, id)) && (editMode || chainOf(id)[0] === id))
  const navigationEntries: [StatisticsView, UiKey][] = []
  for (const entry of visiblePageEntries) {
    navigationEntries.push(entry)
    if (chainOf(entry[0]).includes('resources') && !navigationEntries.some(([id]) => id === 'management')) navigationEntries.push(['management', 'nav.resources'])
  }
  // 资源趋势被隐藏时，管理入口仍需可达；它不参与统计卡片的组合与排序。
  if (!navigationEntries.some(([id]) => id === 'management')) navigationEntries.unshift(['management', 'nav.resources'])
  const placedPages = layout.slots.flat()
  const freePages = pageIds.filter(id => !placedPages.includes(id))
  const pageLabels = Object.fromEntries(pageEntries.map(([id, label]) => [id, ui(label)])) as Record<string, string>

  const placeInSlot = (rowIndex: number, page: Category) => {
    const rows = rowIndex < 0
      ? [...layout.slots, [page]]
      : layout.slots.map((row, index) => index === rowIndex ? [...row, page] : row)
    applyLayout(applySlots(layout, rows))
  }

  const removeFromSlot = (page: Category) => {
    const rows = layout.slots.map(row => row.filter(item => item !== page)).filter(row => row.length > 0)
    applyLayout(applySlots(layout, rows))
  }
  const togglePage = (id: Category, enabled: boolean) => {
    applyLayout(setPageEnabled(layout, id, enabled))
    if (!enabled && id === category) {
      const rest = pageIds.filter(item => item !== id && isPageEnabled(layout, item))
      if (rest.length) setCategory(rest[0])
    }
  }

  /* 单页视图把所有页面合到一条内容里，此时点目录栏改为跳到该页位置。 */
  const selectPage = (id: StatisticsView) => {
    setSearchParams(id === 'management' ? {view: 'management'} : {})
    if (id === 'management') return
    setCategory(id)
    if (singleView) document.querySelector(`[data-card-key^="${id}:"]`)?.scrollIntoView({block: 'start'})
  }

  const movePageBy = (page: Category, delta: number) => {
    const from = layout.pages.findIndex(chain => chain.includes(page))
    const to = from + delta
    if (from < 0 || to < 0 || to >= layout.pages.length) return
    const next = movePageBeside(layout, page, layout.pages[to][0], delta > 0)
    if (next !== layout) applyLayout(next)
  }

  const linkCards = (page: Category, view: PageView, left: string, right: string) => applyLayout({...layout, cards: {...layout.cards, [cardSpace(layout, page)]: rechain(linkChains(view.chains, left, right), keyListFor(page, left, right))}})
  const splitCards = (page: Category, view: PageView, left: string, right: string) => applyLayout({...layout, cards: {...layout.cards, [cardSpace(layout, page)]: splitChains(view.chains, keyListFor(page, left, right), left, right)}})
  /* 隐藏把这张卡从链里摘掉，并在它的位置断链：被隐藏的卡不再参与连接，左右两张卡也不再相连。 */
  const hideKey = (page: Category, _view: PageView, key: string) => {
    /* 链已在 hideCard 里于隐藏处断开，这里只按显示中的顺序修正各链成员。 */
    const next = hideCard(layout, key)
    const space = cardSpace(layout, page)
    const order = orderCards(next, page, spaceKeysOf(page)).filter(item => !isCardHidden(next, item))
    applyLayout({...next, cards: {...next.cards, [space]: rechain(next.cards[space] ?? [], order)}})
  }
  /* 取消隐藏与拖动落位同属插入：插入点两侧已组合时三者连成一条，未组合则不连。 */
  const showKey = (page: Category, view: PageView, key: string) => applyChains(page, view, showCard(layout, key), key)

  /* 移位同时修正链：与不再相邻的伙伴断开，落进两张同链卡之间时并入该链。 */
  const moveCard = (page: Category, view: PageView, key: string, index: number) => {
    const placed = placeCard(layout, page, spaceKeysOf(page), key, index)
    const ordered = orderCards(placed, page, spaceKeysOf(page)).filter(item => !isCardHidden(placed, item))
    applyLayout({...placed, cards: {...placed.cards, [cardSpace(placed, page)]: rechain(readChains(placed, page, view.chains), ordered, key)}})
  }

  /* 指针拖动：落点由指针位置实时判定，拖动中只有被拖卡片与目标卡片改变外观。 */
  useEffect(() => {
    if (!draggingKey) return
    const dragged = draggingKey
    /* 接缝层浮在相邻两张卡的边缘上，落点落在它上面时按指针在接缝上下侧归到对应卡片。 */
    const cardAt = (x: number, y: number) => {
      const hit = document.elementFromPoint(x, y)
      const seam = hit?.closest('.stat-card-seam')
      if (seam) {
        const above = y < seam.getBoundingClientRect().top
        const near = (above ? seam.previousElementSibling : seam.nextElementSibling) as HTMLElement | null
        const nearKey = near?.dataset.cardKey
        if (!nearKey || nearKey === draggingKey) return null
        return {key: nearKey, after: above}
      }
      const card = hit?.closest('.stat-card') as HTMLElement | null
      const key = card?.dataset.cardKey
      if (!card || !key || key === draggingKey) return null
      const rect = card.getBoundingClientRect()
      return {key, after: y > rect.top + rect.height / 2}
    }
    const move = (event: PointerEvent) => setDropTarget(cardAt(event.clientX, event.clientY))
    const up = (event: PointerEvent) => {
      const target = cardAt(event.clientX, event.clientY)
      const dragPage = dragged.split(':')[0] as Category
      const dragView = pageView(dragPage, data)
      const current = orderCards(layout, dragPage, spaceKeysOf(dragPage))
      const from = current.indexOf(draggingKey)
      setDraggingKey(null)
      setDropTarget(null)
      if (!target) return
      let to = current.indexOf(target.key) + (target.after ? 1 : 0)
      if (from < to) to -= 1
      moveCard(dragPage, dragView, dragged, to)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', up)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', up)
    }
  }, [draggingKey, layout, data])

  /* 连接符落在承载那段空白的元素上：可见卡后面紧邻隐藏卡时由占位条承接，纵向居中于两侧卡片之间。 */
  const junctionButton = (page: Category, view: PageView, left: string, right: string) => {
    const linked = isLinked(view.chains, left, right)
    return <button type="button" className={`stat-card-junction${linked ? ' is-linked' : ''}`} aria-label={ui(linked ? 'stats.unlinkCards' : 'stats.linkCards')} title={ui(linked ? 'stats.unlinkCards' : 'stats.linkCards')} onClick={() => linked ? splitCards(page, view, left, right) : linkCards(page, view, left, right)}>{linked ? <span className="stat-card-bar"/> : <Plus size={15}/>}</button>
  }

  /* 收获卡片标题带页面前缀，形如「大世界总结·收获」；卡片态与表格态共用同一个标题。 */
  const renderCard = (page: Category, view: PageView, report: StatisticsReport | undefined, key: string, index: number, boundary?: string) => {
    const metricsTitle = `${ui(categories[page])}·${ui('stats.metricsTitle')}`
    const metricsTable = report ? metricsTableData(metricsTitle, report.metrics) : undefined
    /* 隐藏卡的占位条由前一张可见卡的接缝层承载，接缝因此只画一个连接符。 */
    if (isCardHidden(layout, key)) {
      /* 前面没有可见卡的隐藏卡由自己渲染占位条。 */
      const claimed = view.spaceOrder.slice(0, view.spaceOrder.indexOf(key)).some(item => !isCardHidden(layout, item))
      if (claimed) return null
      return <div className="stat-card-hidden" key={key}>
        <button type="button" className="text-button" aria-label={ui('stats.showCard')} title={ui('stats.showCard')} onClick={() => showKey(page, view, key)}><Eye size={15}/></button>
      </div>
    }
    const table = view.tableKeys.includes(key) ? report!.tables.find(item => cardKey(page, `table:${item.title}`) === key) : undefined
    const drop = dropTarget?.key === key ? (dropTarget.after ? ' is-drop-after' : ' is-drop-before') : ''
    const bar = editMode ? <div className="stat-card-edit-bar">
      <button type="button" className="text-button" disabled={index === 0} aria-label={ui('stats.orderUp')} title={ui('stats.orderUp')} onClick={() => moveCard(page, view, key, index - 1)}><ArrowUp size={15}/></button>
      <button type="button" className="stat-card-drag-handle" aria-label={ui('stats.orderHandle')} title={ui('stats.orderHandle')} onPointerDown={event => { event.preventDefault(); setDraggingKey(key) }}><GripVertical size={15}/></button>
      <button type="button" className="text-button" disabled={index === spaceKeysOf(page).length - 1} aria-label={ui('stats.orderDown')} title={ui('stats.orderDown')} onClick={() => moveCard(page, view, key, index + 1)}><ArrowDown size={15}/></button>
    </div> : null
    /* 下一张按显示中的顺序取：隐藏卡是断开状态、不参与连接，它自己不出连接符。 */
    const next = isCardHidden(layout, key) ? undefined : view.visibleKeys[view.visibleKeys.indexOf(key) + 1] ?? boundary
    const from = view.spaceOrder.indexOf(key)
    const until = next ? view.spaceOrder.indexOf(next) : -1
    const slots = view.spaceOrder.slice(from + 1, until > from ? until : undefined).filter(item => isCardHidden(layout, item))
    /* 占位条只在编辑模式出现：非编辑模式下隐藏卡不留痕迹。 */
    const seam = next || slots.length > 0
      ? <div className={`stat-card-seam${next && isLinked(view.chains, key, next) ? ' is-linked' : ''}`}>{editMode ? slots.map(item => <div className="stat-card-hidden" key={item}>
        <button type="button" className="text-button" aria-label={ui('stats.showCard')} title={ui('stats.showCard')} onClick={() => showKey(page, view, item)}><Eye size={15}/></button>
      </div>) : null}{editMode && next ? junctionButton(page, view, key, next) : null}</div>
      : null
    const hide = editMode ? <button type="button" className="text-button stat-card-hide" aria-label={ui('stats.hideCard')} title={ui('stats.hideCard')} onClick={() => hideKey(page, view, key)}><EyeOff size={15}/></button> : null
    const className = `${view.cardClass(key)}${key === view.chartKey && isCardFolded(layout, view.plotKey) ? ' is-plot-folded' : ''}${draggingKey === key ? ' is-dragging' : ''}${drop}`
    return <Fragment key={key}><div data-card-key={key} className={className}>{bar}{key === view.metricsKey
      ? <><section className="panel summary-metrics-panel">{isMetricsTable(layout, page) ? <StatisticsTable data={metricsTable!} foldControl={view.foldControl(view.metricsKey)} editControls={editMode ? <><button type="button" className="text-button statistics-metrics-table" aria-pressed={isMetricsTable(layout, page)} aria-label={ui('stats.cardMode')} title={ui('stats.cardMode')} onClick={() => applyLayout(setMetricsTable(layout, page, false))}>{ui('stats.cardMode')}</button>{tableSettings(view.metricsKey, metricsTable!)}</> : undefined}/> : <><div className="panel-heading"><div><h3>{metricsTitle}</h3>{editMode ? <button type="button" className="text-button statistics-metrics-table" aria-pressed={isMetricsTable(layout, page)} aria-label={isMetricsTable(layout, page) ? ui('stats.cardMode') : ui('stats.metricsTable')} title={isMetricsTable(layout, page) ? ui('stats.cardMode') : ui('stats.metricsTable')} onClick={() => applyLayout(setMetricsTable(layout, page, !isMetricsTable(layout, page)))}>{isMetricsTable(layout, page) ? ui('stats.cardMode') : ui('stats.metricsTable')}</button> : undefined}</div><div className="stat-card-actions">{view.foldControl(view.metricsKey)}</div></div><div className="stat-metrics summary-metrics">{report!.metrics.map(item => {
    return <div key={item.label} className="summary-metric-card">
      <div className="summary-metric-head">
        <span className="summary-metric-label">{item.label}</span>
        {metricIcon(item)}
      </div>
      <strong>{item.value == null ? '—' : item.value.toLocaleString(undefined, {maximumFractionDigits: 2})}<small>{item.unit}</small></strong>
    </div>
  })}</div></>}</section></>
      : key === view.chartKey
        ? <Suspense fallback={<Loading/>}><StatisticsChart key={page} category={page} compact={isChartCompact(layout, page)} compactControl={editMode ? <button type="button" className="text-button statistics-compact-toggle" aria-pressed={isChartCompact(layout, page)} aria-label={isChartCompact(layout, page) ? ui('stats.cardMode') : ui('stats.compactHeader')} title={isChartCompact(layout, page) ? ui('stats.cardMode') : ui('stats.compactHeader')} onClick={() => applyLayout(setChartCompact(layout, page, !isChartCompact(layout, page)))}>{isChartCompact(layout, page) ? ui('stats.cardMode') : ui('stats.compactHeader')}</button> : undefined} showPicker={Boolean(editMode) || !isPickerHidden(layout, page)} pickerMuted={isPickerHidden(layout, page)} stackedRise={isStackedRise(layout, page)} stackedControl={editMode ? <button type="button" className="text-button statistics-stacked-rise" aria-pressed={isStackedRise(layout, page)} aria-label={isStackedRise(layout, page) ? ui('stats.plainColor') : ui('stats.stackedRise')} title={isStackedRise(layout, page) ? ui('stats.plainColor') : ui('stats.stackedRise')} onClick={() => applyLayout(setStackedRise(layout, page, !isStackedRise(layout, page)))}>{isStackedRise(layout, page) ? ui('stats.plainColor') : ui('stats.stackedRise')}</button> : undefined} pickerControl={editMode ? <button type="button" className="text-button statistics-picker-toggle" aria-pressed={isPickerHidden(layout, page)} aria-label={isPickerHidden(layout, page) ? ui('stats.showPicker') : ui('stats.hidePicker')} title={isPickerHidden(layout, page) ? ui('stats.showPicker') : ui('stats.hidePicker')} onClick={() => applyLayout(setPickerHidden(layout, page, !isPickerHidden(layout, page)))}>{isPickerHidden(layout, page) ? ui('stats.showPicker') : ui('stats.hidePicker')}</button> : undefined} zeroBase={zeroBase} zeroBaseControl={editMode ? <button type="button" className="text-button statistics-zero-base" aria-pressed={zeroBase} aria-label={zeroBase ? ui('stats.axisAuto') : ui('stats.zeroBase')} title={zeroBase ? ui('stats.axisAuto') : ui('stats.zeroBase')} onClick={() => setZeroBase(!zeroBase)}>{zeroBase ? ui('stats.axisAuto') : ui('stats.zeroBase')}</button> : undefined} filtered={layout.filteredSeries[page] ?? []} onToggleFilter={key => applyLayout(toggleSeriesFilter(layout, page, key))} series={report!.series} heading={!condensed} expanded={expandedChart === page} onToggleExpanded={() => toggleExpanded(page)} title={ui(categories[page])} foldControl={condensed ? undefined : view.foldControl(view.chartKey)} plotFoldControl={view.foldControl(view.plotKey, 'corner', 'stats.foldChart', 'stats.unfoldChart')}/></Suspense>
        : key === view.rawKey
          ? <section className="panel"><StatisticsTable data={rawTableOf(page, report)!} foldControl={view.foldControl(view.rawKey)} {...tableDisplay(layout, view.rawKey)} editControls={editMode ? tableSettings(view.rawKey, rawTableOf(page, report)!) : undefined}/></section>
          : <section className="panel"><StatisticsTable data={table!} foldControl={view.foldControl(key)} {...tableDisplay(layout, key)} editControls={editMode ? tableSettings(key, table!) : undefined}/></section>}{hide}</div>{seam}</Fragment>
  }

  /* 单张表格的设置：每页行数、补图标、简洁显示；一表一份，互不影响。 */
  const tableSettings = (cardKey: string, table: StatTable) => {
    const display = tableDisplay(layout, cardKey)
    const showRows = table.rows.length > DEFAULT_TABLE_ROWS
    /* 简洁模式把每个数据行压成一行文字，靠图标代替列名。 */
    const showIcons = hasTableIcons(table)
    const showPlain = showIcons
    if (!showRows && !showIcons) return undefined
    return (
      <div className="statistics-table-settings">
        {showRows && <label className="statistics-table-rows">
          <NumberDraftInput value={display.rows} label={ui('stats.tableRows')} onCommit={rows => applyLayout(setTableDisplay(layout, cardKey, {rows}))}/>
          {ui('stats.tableRows')}
        </label>}
        {showIcons && <button type="button" className="text-button statistics-table-icons" aria-pressed={display.icons} disabled={display.plain}
          aria-label={display.icons ? ui('stats.tableNoIcons') : ui('stats.tableIcons')} title={display.icons ? ui('stats.tableNoIcons') : ui('stats.tableIcons')}
          onClick={() => applyLayout(setTableDisplay(layout, cardKey, {icons: !display.icons}))}>{display.icons ? ui('stats.tableNoIcons') : ui('stats.tableIcons')}</button>}
        {showPlain && <button type="button" className="text-button statistics-table-plain" aria-pressed={display.plain}
          aria-label={display.plain ? ui('stats.tableNormal') : ui('stats.tablePlain')} title={display.plain ? ui('stats.tableNormal') : ui('stats.tablePlain')}
          onClick={() => applyLayout(setTableDisplay(layout, cardKey, {plain: !display.plain}))}>{display.plain ? ui('stats.tableNormal') : ui('stats.tablePlain')}</button>}
      </div>
    )
  }

  const categoryControl = <SegmentedControl<StatisticsView> className="statistics-category-control" label={ui('stats.categoryLabel')} value={management ? 'management' : category} onChange={selectPage} onItemContextMenu={editMode && !management ? id => {if (id !== 'management') togglePage(id, false)} : undefined} onItemMove={editMode && !management ? (id, delta) => {if (id !== 'management') movePageBy(id, delta)} : undefined} itemClassName={id => id === 'management' ? '' : `${isPageEnabled(layout, id) ? '' : 'is-disabled'}${!editMode && chainOf(id).length > 1 ? ' is-chained' : ''}`.trim()} trailing={!management && singleViewToggle} options={navigationEntries.map(([value, label]) => ({value, label: ui(label)}))}/>
  const content = <>
    {condensed
      ? <div className={`statistics-toolbar-row${compact ? ' is-compact' : ''}`} ref={toolbarRow}>
          {categoryControl}
          {/* 放不下时改用单按钮下拉；指针移入或键盘聚焦即展开，见 Select 的 openOnFocus */}
          <Select openOnFocus className="statistics-category-select" aria-label={ui('stats.categoryLabel')} value={management ? 'management' : category} onChange={event => selectPage(event.target.value as StatisticsView)}>
            {navigationEntries.map(([value, label]) => <option value={value} key={value}>{ui(label)}</option>)}
          </Select>
          <div className="statistics-toolbar-right" ref={toolbarRight}>{!management && <>{hasChart && activeView.foldControl(activeView.chartKey)}{hasChart && <button className="text-button" onClick={() => category && toggleExpanded(category)}>{expandedChart === category ? ui('stats.collapseChart') : ui('stats.expandChart')}</button>}{rangeControls}<ActionGroup>{actions}</ActionGroup></>}</div>
        </div>
      : <>
          <div className="statistics-toolbar-row">
            {categoryControl}
            {legacy && !management && <ActionGroup>{actions}</ActionGroup>}
          </div>
          {!management && <div className="statistics-controls period-controls"><strong>{ui(categories[category!])}</strong>{rangeControls}{hints}</div>}
        </>}
    {condensed && !management && (category === 'ships' || category === 'loot') && <div className="statistics-controls period-controls">{hints}</div>}
    {editMode && !management && <StatisticsEditConsole customized={customized} pages={fixedPageOrder.map(id => ({id, label: ui(categories[id]), enabled: isPageEnabled(layout, id)}))} onTogglePage={id => togglePage(id, !isPageEnabled(layout, id))} onReset={resetLayout}>
      {/* 顺序控件：一次挪一格，组合链整体挪动。 */}
      <div className="statistics-page-order">
        {pageEntries.map(([id, label]) => {
          const at = layout.pages.findIndex(chain => chain.includes(id))
          return (
            <span className="statistics-page-order-item" key={id}>
              <button type="button" aria-label={`${ui(label)} 前移`} disabled={at <= 0} onClick={() => movePageBy(id, -1)}>◀</button>
              <span className="statistics-page-order-label">{ui(label)}</span>
              <button type="button" aria-label={`${ui(label)} 后移`} disabled={at < 0 || at >= layout.pages.length - 1} onClick={() => movePageBy(id, 1)}>▶</button>
            </span>
          )
        })}
      </div>
      <PageChainSlots rows={layout.slots} labels={pageLabels} options={freePages} onPlace={placeInSlot} onRemove={removeFromSlot}/>
    </StatisticsEditConsole>}
    {/* 分节：每个卡片空间一段内容，链与顺序都在空间全量上算，跨页的链落进同一个容器。 */}
    {management ? <Suspense fallback={<Loading/>}><ResourceManagement key={instance}/></Suspense> : <>
    {storageError && <ErrorBox message={storageError}/>}
    <div className="statistics-page-sections">
      {(singleView ? [spaceOf(category!)] : isPageEnabled(layout, category) ? [chainOf(category)] : []).map(space => {
        const head = space[0]
        const view = spaceView(space)
        const error = space.map(page => chainError[page]).find(Boolean) ?? ''
        const ready = space.every(page => chainData[page] !== undefined)
        /* 每张卡按所属页自己的视图渲染：卡片形态由该页的数据决定。 */
        const draw = (key: string, next?: string) => {
          const page = key.slice(0, key.indexOf(':')) as Category
          const report = chainData[page]
          return report ? renderCard(page, pageView(page, report), report, key, view.ordered.indexOf(key), next) : null
        }
        return <Fragment key={head}>
          {space.map(page => <CategorySection key={page} params={{instance, category: page, days, month, period, researchSeries, lootTask, includeSeries: pageNeedsSeries(layout, page)}} revision={revision}
            onState={state => reportOf(page, state.data, state.error)} render={() => null}/>)}
          <section className="statistics-page-section">
            {error ? <ErrorBox message={error} retry={() => setRevision(value => value + 1)}/>
              : !ready ? <Loading/>
                : <div className={`statistics-sections${editMode ? ' is-editing' : ''}`}>
                  {view.runs.map(run => run.keys.length > 1
                    ? <div className="stat-card-chain" key={run.keys[0]}>{run.keys.map(key => draw(key, view.visible[view.visible.indexOf(key) + 1]))}</div>
                    : draw(run.keys[0], view.visible[view.visible.indexOf(run.keys[0]) + 1]))}
                </div>}
          </section>
        </Fragment>
      })}
    </div>
    </>}
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
    : <><PageTitle className="statistics-page-title" title={ui('nav.statistics')} actions={!management && actions}/>{content}</>
}
