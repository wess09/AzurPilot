/**
 * 从 Statistics.tsx 原 285-299、544-585 行提取，纯搬迁未改动。
 * 统计页工具栏：动作按钮、筛选控件、分类切换与单表设置控件。
 */
import type {ReactNode} from 'react'
import {Download, Paintbrush, Play, RefreshCw} from 'lucide-react'
import {Button} from '../../components/ui/button'
import {Select, SelectContent, SelectItem, SelectTrigger, SelectValue} from '../../components/official-ui/select'
import {Input} from '../../components/official-ui/input'
import {Tabs, TabsList, TabsTrigger} from '../../components/ui/tabs'
import {DEFAULT_TABLE_ROWS, isPageEnabled, setTableDisplay, tableDisplay} from '../../app/statisticsLayout'
import type {StatisticsLayout} from '../../app/statisticsLayout'
import type {UiKey, UiTranslator} from '../../i18n'
import type { StatTable, StatisticsReport } from '../../api/types'
import type {useConnection} from '../../app/context'
import type {Category, StatisticsView} from './shared'
import {NumberDraftInput, hasTableIcons} from './table-utils'

interface ToolbarContext {
  ui: UiTranslator
  category: Category
  days: number
  month: string
  period: 'day' | 'week' | 'month'
  researchSeries: string
  lootTask: string
  data: StatisticsReport | undefined
  setDays: (next: number) => void
  setMonth: (next: string) => void
  setPeriod: (next: 'day' | 'week' | 'month') => void
  setResearchSeries: (next: string) => void
  setLootTask: (next: string) => void
  connection: ReturnType<typeof useConnection>
  startingStorage: boolean
  refreshing: boolean
  runStorageStatistics: () => Promise<void>
  refresh: () => Promise<void>
  download: () => void
  editMode: boolean
  toggleEditMode: () => void
  layout: StatisticsLayout
  applyLayout: (next: StatisticsLayout) => void
  management: boolean
  selectPage: (id: StatisticsView) => void
  navigationEntries: [StatisticsView, UiKey][]
  chainOf: (page: Category) => Category[]
  singleViewToggle: ReactNode
  togglePage: (id: Category, enabled: boolean) => void
  movePageBy: (page: Category, delta: number) => void
}

export function createToolbar({ui, category, days, month, period, researchSeries, lootTask, data, setDays, setMonth, setPeriod, setResearchSeries, setLootTask, connection, startingStorage, refreshing, runStorageStatistics, refresh, download, editMode, toggleEditMode, layout, applyLayout, management, selectPage, navigationEntries, chainOf, singleViewToggle, togglePage, movePageBy}: ToolbarContext) {
  const actions = <>{category === 'storage' && <Button variant="outline" disabled={connection !== 'ready' || startingStorage} onClick={runStorageStatistics}><Play size={15}/>{ui('stats.runStorage')}</Button>}<Button variant="outline" disabled={connection !== 'ready' || refreshing} onClick={refresh}><RefreshCw size={15}/>{refreshing ? ui('stats.refreshing') : ui('stats.refresh')}</Button><Button variant="outline" disabled={!data} onClick={download}><Download size={15}/>{ui('stats.exportCategory')}</Button><Button variant={editMode ? 'default' : 'outline'} aria-pressed={editMode} onClick={toggleEditMode}><Paintbrush size={15}/>{ui('stats.editMode')}</Button></>
  const rangeControls = <>
    {(category === 'resources' || category === 'storage') && period === 'day' && <label className="statistics-inline-control"><span className="statistics-inline-label">{ui('stats.range')}</span><Select value={String(days)} onValueChange={value => setDays(Number(value))}><SelectTrigger aria-label={ui('stats.days')}><SelectValue/></SelectTrigger><SelectContent>{[1, 7, 30, 90, 365].map(value => <SelectItem value={String(value)} key={value}>{ui('stats.recentDays', {days: value})}</SelectItem>)}</SelectContent></Select></label>}
    {/* 月份输入框自带日期格式，使用可访问名称区分控件。 */}
    {(['action', 'opsi', 'commission', 'loot', 'resources', 'storage'].includes(category!) || category === 'research') && <label className="statistics-inline-control"><Input aria-label={ui('stats.month')} type="month" min="2020-01" max="9998-12" value={month} disabled={(['commission', 'research', 'loot', 'resources', 'storage'].includes(category!)) && period !== 'month'} onChange={event => {if (event.target.value) setMonth(event.target.value)}}/></label>}
    {category === 'research' && <label className="statistics-inline-control"><span className="statistics-inline-label">{ui('stats.researchSeries')}</span><Select value={researchSeries} onValueChange={setResearchSeries}><SelectTrigger aria-label={ui('stats.researchSeries')}><SelectValue/></SelectTrigger><SelectContent>{[1, 2, 3, 4, 5, 6, 7, 8, 9].map(value => <SelectItem value={String(value)} key={value}>{ui('stats.seriesN', {n: value})}</SelectItem>)}<SelectItem value="consumable">{ui('stats.consumableScope')}</SelectItem></SelectContent></Select></label>}
    {(category === 'resources' || category === 'storage' || category === 'commission' || category === 'research') && <label className="statistics-inline-control"><span className="statistics-inline-label">{ui('stats.period')}</span><Select value={period} onValueChange={value => setPeriod(value as typeof period)}><SelectTrigger aria-label={ui(category === 'commission' ? 'stats.commissionPeriod' : 'stats.period')}><SelectValue/></SelectTrigger><SelectContent><SelectItem value="day">{category === 'resources' || category === 'storage' ? ui('stats.recentDays', {days}) : ui('stats.today')}</SelectItem><SelectItem value="week">{ui('stats.thisWeek')}</SelectItem><SelectItem value="month">{ui('stats.selectedMonth')}</SelectItem></SelectContent></Select></label>}
    {/* 大世界掉落：任务筛选的选项来自后端（含当前窗口内没记录的任务），值就是任务标识。 */}
    {category === 'loot' && <label className="statistics-inline-control"><span className="statistics-inline-label">{ui('stats.lootTask')}</span><Select value={lootTask || '__all__'} onValueChange={value => setLootTask(value === '__all__' ? '' : value)}><SelectTrigger aria-label={ui('stats.lootTask')}><SelectValue/></SelectTrigger><SelectContent><SelectItem value="__all__">{ui('stats.lootTaskAll')}</SelectItem>{(data?.taskOptions ?? []).map(item => <SelectItem value={item.key} key={item.key}>{item.count ? `${item.label}（${item.count}）` : item.label}</SelectItem>)}</SelectContent></Select></label>}
    {category === 'loot' && <label className="statistics-inline-control"><span className="statistics-inline-label">{ui('stats.period')}</span><Select value={period} onValueChange={value => setPeriod(value as typeof period)}><SelectTrigger aria-label={ui('stats.period')}><SelectValue/></SelectTrigger><SelectContent><SelectItem value="day">{ui('stats.today')}</SelectItem><SelectItem value="week">{ui('stats.thisWeek')}</SelectItem><SelectItem value="month">{ui('stats.selectedMonth')}</SelectItem></SelectContent></Select></label>}
  </>
  const hints = <>
    {category === 'ships' && <span>{ui('stats.shipHint')}</span>}
    {category === 'loot' && <span>{ui('stats.lootHint')}</span>}
  </>

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
        {showIcons && <Button type="button" variant="ghost" size="sm" aria-pressed={display.icons} disabled={display.plain}
          aria-label={display.icons ? ui('stats.tableNoIcons') : ui('stats.tableIcons')} title={display.icons ? ui('stats.tableNoIcons') : ui('stats.tableIcons')}
          onClick={() => applyLayout(setTableDisplay(layout, cardKey, {icons: !display.icons}))}>{display.icons ? ui('stats.tableNoIcons') : ui('stats.tableIcons')}</Button>}
        {showPlain && <Button type="button" variant="ghost" size="sm" aria-pressed={display.plain}
          aria-label={display.plain ? ui('stats.tableNormal') : ui('stats.tablePlain')} title={display.plain ? ui('stats.tableNormal') : ui('stats.tablePlain')}
          onClick={() => applyLayout(setTableDisplay(layout, cardKey, {plain: !display.plain}))}>{display.plain ? ui('stats.tableNormal') : ui('stats.tablePlain')}</Button>}
      </div>
    )
  }

  const categoryControl = <Tabs className="statistics-category-control" value={management ? 'management' : category} onValueChange={value => selectPage(value as StatisticsView)}>
    <TabsList aria-label={ui('stats.categoryLabel')}>
      {navigationEntries.map(([id, label]) => <TabsTrigger key={id} value={id}
        className={id === 'management' ? undefined : `${isPageEnabled(layout, id) ? '' : 'is-disabled'}${!editMode && chainOf(id).length > 1 ? ' is-chained' : ''}`.trim()}
        onContextMenu={editMode && !management ? event => {event.preventDefault(); if (id !== 'management') togglePage(id, false)} : undefined}
        onKeyDown={editMode && !management ? event => {if (event.altKey && (event.key === 'ArrowRight' || event.key === 'ArrowLeft')) {event.preventDefault(); event.stopPropagation(); if (id !== 'management') movePageBy(id, event.key === 'ArrowRight' ? 1 : -1)}} : undefined}
      >{ui(label)}</TabsTrigger>)}
      {!management && singleViewToggle}
    </TabsList>
  </Tabs>
  /* 窄屏用明确的下拉入口展示全部分类，编辑模式的合并开关仍可单独操作。 */
  const categoryPicker = <div className="statistics-category-picker">
    <Select value={management ? 'management' : category} onValueChange={value => selectPage(value as StatisticsView)}>
      <SelectTrigger className="statistics-category-select" aria-label={ui('stats.categoryLabel')}><SelectValue/></SelectTrigger>
      <SelectContent>{navigationEntries.map(([value, label]) => <SelectItem value={value} key={value}>{ui(label)}</SelectItem>)}</SelectContent>
    </Select>
    {!management && singleViewToggle}
  </div>

  return {actions, rangeControls, hints, categoryControl, categoryPicker, tableSettings}
}
