/**
 * 从 Statistics.tsx 原 494-542 行提取，纯搬迁未改动。
 * 单张统计卡片的渲染：收获指标、图表、原始记录表与明细表卡。
 */
import {Fragment, Suspense, type Dispatch, type LazyExoticComponent, type ReactNode, type SetStateAction} from 'react'
import {ArrowDown, ArrowUp, Eye, EyeOff, GripVertical} from 'lucide-react'
import {Button} from '../../components/ui/button'
import {Loading} from '../../components/ui'
import { StatisticsTable } from '../../components/StatisticsTable'
import {cardKey, isCardFolded, isCardHidden, isChartCompact, isLinked, isMetricsTable, isPickerHidden, isStackedRise, setChartCompact, setMetricsTable, setPickerHidden, setStackedRise, tableDisplay, toggleSeriesFilter} from '../../app/statisticsLayout'
import type {StatisticsLayout} from '../../app/statisticsLayout'
import type {UiTranslator} from '../../i18n'
import type { StatTable, StatisticsReport } from '../../api/types'
import {categories} from './shared'
import type {Category} from './shared'
import {metricsTableData} from './table-utils'
import {metricIcon} from './metric-icon'
import type {PageView} from './card-model'
import type {useStatisticsData} from './use-statistics-data'

type StatisticsData = ReturnType<typeof useStatisticsData>

interface CardRenderContext {
  ui: UiTranslator
  layout: StatisticsLayout
  editMode: boolean
  dropTarget: {key: string, after: boolean} | null
  draggingKey: string | null
  setDraggingKey: Dispatch<SetStateAction<string | null>>
  applyLayout: (next: StatisticsLayout) => void
  spaceKeysOf: (page: Category) => string[]
  showKey: (page: Category, view: PageView, key: string) => void
  moveCard: (page: Category, view: PageView, key: string, index: number) => void
  hideKey: (page: Category, view: PageView, key: string) => void
  junctionButton: (page: Category, view: PageView, left: string, right: string) => ReactNode
  expandedChart: string | null
  toggleExpanded: (page: string) => void
  zeroBase: boolean
  setZeroBase: (next: boolean) => void
  rawTableOf: StatisticsData['rawTableOf']
  tableSettings: (cardKey: string, table: StatTable) => ReactNode
  StatisticsChart: LazyExoticComponent<typeof import('../../components/StatisticsChart')['StatisticsChart']>
}

/* 收获卡片标题带页面前缀，形如「大世界总结·收获」；卡片态与表格态共用同一个标题。 */
export function renderCard({ui, layout, editMode, dropTarget, draggingKey, setDraggingKey, applyLayout, spaceKeysOf, showKey, moveCard, hideKey, junctionButton, expandedChart, toggleExpanded, zeroBase, setZeroBase, rawTableOf, tableSettings, StatisticsChart}: CardRenderContext, page: Category, view: PageView, report: StatisticsReport | undefined, key: string, index: number, boundary?: string) {
  const metricsTitle = `${ui(categories[page])}·${ui('stats.metricsTitle')}`
  const metricsTable = report ? metricsTableData(metricsTitle, report.metrics) : undefined
  /* 隐藏卡的占位条由前一张可见卡的接缝层承载，接缝因此只画一个连接符。 */
  if (isCardHidden(layout, key)) {
    /* 前面没有可见卡的隐藏卡由自己渲染占位条。 */
    const claimed = view.spaceOrder.slice(0, view.spaceOrder.indexOf(key)).some(item => !isCardHidden(layout, item))
    if (claimed) return null
    return <div className="stat-card-hidden" key={key}>
      <Button type="button" variant="ghost" size="icon-xs" aria-label={ui('stats.showCard')} title={ui('stats.showCard')} onClick={() => showKey(page, view, key)}><Eye/></Button>
    </div>
  }
  const table = view.tableKeys.includes(key) ? report!.tables.find(item => cardKey(page, `table:${item.title}`) === key) : undefined
  const drop = dropTarget?.key === key ? (dropTarget.after ? ' is-drop-after' : ' is-drop-before') : ''
  const bar = editMode ? <div className="stat-card-edit-bar">
    <Button type="button" variant="ghost" size="icon-xs" disabled={index === 0} aria-label={ui('stats.orderUp')} title={ui('stats.orderUp')} onClick={() => moveCard(page, view, key, index - 1)}><ArrowUp/></Button>
    <button type="button" className="stat-card-drag-handle" aria-label={ui('stats.orderHandle')} title={ui('stats.orderHandle')} onPointerDown={event => { event.preventDefault(); setDraggingKey(key) }}><GripVertical size={15}/></button>
    <Button type="button" variant="ghost" size="icon-xs" disabled={index === spaceKeysOf(page).length - 1} aria-label={ui('stats.orderDown')} title={ui('stats.orderDown')} onClick={() => moveCard(page, view, key, index + 1)}><ArrowDown/></Button>
  </div> : null
  /* 下一张按显示中的顺序取：隐藏卡是断开状态、不参与连接，它自己不出连接符。 */
  const next = isCardHidden(layout, key) ? undefined : view.visibleKeys[view.visibleKeys.indexOf(key) + 1] ?? boundary
  const from = view.spaceOrder.indexOf(key)
  const until = next ? view.spaceOrder.indexOf(next) : -1
  const slots = view.spaceOrder.slice(from + 1, until > from ? until : undefined).filter(item => isCardHidden(layout, item))
  /* 占位条只在编辑模式出现：非编辑模式下隐藏卡不留痕迹。 */
  const seam = next || slots.length > 0
    ? <div className={`stat-card-seam${next && isLinked(view.chains, key, next) ? ' is-linked' : ''}`}>{editMode ? slots.map(item => <div className="stat-card-hidden" key={item}>
      <Button type="button" variant="ghost" size="icon-xs" aria-label={ui('stats.showCard')} title={ui('stats.showCard')} onClick={() => showKey(page, view, item)}><Eye/></Button>
    </div>) : null}{editMode && next ? junctionButton(page, view, key, next) : null}</div>
    : null
  const hide = editMode ? <Button type="button" variant="ghost" size="icon-xs" className="stat-card-hide" aria-label={ui('stats.hideCard')} title={ui('stats.hideCard')} onClick={() => hideKey(page, view, key)}><EyeOff/></Button> : null
  const className = `${view.cardClass(key)}${key === view.chartKey && isCardFolded(layout, view.plotKey) ? ' is-plot-folded' : ''}${draggingKey === key ? ' is-dragging' : ''}${drop}`
  return <Fragment key={key}><div data-card-key={key} className={className}>{bar}{key === view.metricsKey
    ? <><section className="panel summary-metrics-panel">{isMetricsTable(layout, page) ? <StatisticsTable data={metricsTable!} foldControl={view.foldControl(view.metricsKey)} editControls={editMode ? <><Button type="button" variant="ghost" size="sm" aria-pressed={isMetricsTable(layout, page)} aria-label={ui('stats.cardMode')} title={ui('stats.cardMode')} onClick={() => applyLayout(setMetricsTable(layout, page, false))}>{ui('stats.cardMode')}</Button>{tableSettings(view.metricsKey, metricsTable!)}</> : undefined}/> : <><div className="panel-heading"><div><h3>{metricsTitle}</h3>{editMode ? <Button type="button" variant="ghost" size="sm" aria-pressed={isMetricsTable(layout, page)} aria-label={isMetricsTable(layout, page) ? ui('stats.cardMode') : ui('stats.metricsTable')} title={isMetricsTable(layout, page) ? ui('stats.cardMode') : ui('stats.metricsTable')} onClick={() => applyLayout(setMetricsTable(layout, page, !isMetricsTable(layout, page)))}>{isMetricsTable(layout, page) ? ui('stats.cardMode') : ui('stats.metricsTable')}</Button> : undefined}</div><div className="stat-card-actions">{view.foldControl(view.metricsKey)}</div></div><div className="stat-metrics summary-metrics">{report!.metrics.map(item => {
    return <div key={item.label} className="summary-metric-card">
      <div className="summary-metric-head">
        <span className="summary-metric-label">{item.label}</span>
        {metricIcon(item)}
      </div>
      <strong>{item.value == null ? '—' : item.value.toLocaleString(undefined, {maximumFractionDigits: 2})}<small>{item.unit}</small></strong>
    </div>
  })}</div></>}</section></>
    : key === view.chartKey
      ? <Suspense fallback={<Loading/>}><StatisticsChart key={page} category={page} compact={isChartCompact(layout, page)} compactControl={editMode ? <Button type="button" variant="ghost" size="sm" aria-pressed={isChartCompact(layout, page)} aria-label={isChartCompact(layout, page) ? ui('stats.cardMode') : ui('stats.compactHeader')} title={isChartCompact(layout, page) ? ui('stats.cardMode') : ui('stats.compactHeader')} onClick={() => applyLayout(setChartCompact(layout, page, !isChartCompact(layout, page)))}>{isChartCompact(layout, page) ? ui('stats.cardMode') : ui('stats.compactHeader')}</Button> : undefined} showPicker={Boolean(editMode) || !isPickerHidden(layout, page)} pickerMuted={isPickerHidden(layout, page)} stackedRise={isStackedRise(layout, page)} stackedControl={editMode ? <Button type="button" variant="ghost" size="sm" aria-pressed={isStackedRise(layout, page)} aria-label={isStackedRise(layout, page) ? ui('stats.plainColor') : ui('stats.stackedRise')} title={isStackedRise(layout, page) ? ui('stats.plainColor') : ui('stats.stackedRise')} onClick={() => applyLayout(setStackedRise(layout, page, !isStackedRise(layout, page)))}>{isStackedRise(layout, page) ? ui('stats.plainColor') : ui('stats.stackedRise')}</Button> : undefined} pickerControl={editMode ? <Button type="button" variant="ghost" size="sm" aria-pressed={isPickerHidden(layout, page)} aria-label={isPickerHidden(layout, page) ? ui('stats.showPicker') : ui('stats.hidePicker')} title={isPickerHidden(layout, page) ? ui('stats.showPicker') : ui('stats.hidePicker')} onClick={() => applyLayout(setPickerHidden(layout, page, !isPickerHidden(layout, page)))}>{isPickerHidden(layout, page) ? ui('stats.showPicker') : ui('stats.hidePicker')}</Button> : undefined} zeroBase={zeroBase} zeroBaseControl={editMode ? <Button type="button" variant="ghost" size="sm" aria-pressed={zeroBase} aria-label={zeroBase ? ui('stats.axisAuto') : ui('stats.zeroBase')} title={zeroBase ? ui('stats.axisAuto') : ui('stats.zeroBase')} onClick={() => setZeroBase(!zeroBase)}>{zeroBase ? ui('stats.axisAuto') : ui('stats.zeroBase')}</Button> : undefined} filtered={layout.filteredSeries[page] ?? []} onToggleFilter={key => applyLayout(toggleSeriesFilter(layout, page, key))} series={report!.series} expanded={expandedChart === page} onToggleExpanded={() => toggleExpanded(page)} title={ui(categories[page])} foldControl={view.foldControl(view.chartKey)} plotFoldControl={view.foldControl(view.plotKey, 'corner', 'stats.foldChart', 'stats.unfoldChart')}/></Suspense>
      : key === view.rawKey
        ? <section className="panel"><StatisticsTable data={rawTableOf(page, report)!} foldControl={view.foldControl(view.rawKey)} {...tableDisplay(layout, view.rawKey)} editControls={editMode ? tableSettings(view.rawKey, rawTableOf(page, report)!) : undefined}/></section>
        : <section className="panel"><StatisticsTable data={table!} foldControl={view.foldControl(key)} {...tableDisplay(layout, key)} editControls={editMode ? tableSettings(key, table!) : undefined}/></section>}{hide}</div>{seam}</Fragment>
}
