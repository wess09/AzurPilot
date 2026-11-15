/**
 * @fileoverview 数据统计与图表分析页面。
 *
 * 主体逻辑已按内聚单元拆分至 statistics-ui/（纯搬迁）：
 * shared / metric-icon / table-utils / use-statistics-prefs / use-statistics-data /
 * use-statistics-edit / card-model / card-render / toolbar。
 */
import {Button} from '../components/ui/button'
import {Fragment, lazy, Suspense, useEffect, useState} from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { useApp, useConnection } from '../app/context'
import { ActionGroup, ErrorBox, Loading } from '../components/ui'
import { applySlots, isPageEnabled, movePageBeside, orderCards, orderPages, pageNeedsSeries, setPageEnabled } from '../app/statisticsLayout'
import type { UiKey } from '../i18n'
import { CategorySection } from '../components/CategorySection'
import { PageChainSlots } from '../components/PageChainSlots'
import { StatisticsEditConsole } from '../components/StatisticsEditConsole'
import { categories, fixedPageOrder } from './statistics-ui/shared'
import type { Category, StatisticsView } from './statistics-ui/shared'
import { useStatisticsPrefs } from './statistics-ui/use-statistics-prefs'
import { useStatisticsData } from './statistics-ui/use-statistics-data'
import { useStatisticsEdit } from './statistics-ui/use-statistics-edit'
import { createCardModel } from './statistics-ui/card-model'
import { renderCard } from './statistics-ui/card-render'
import { createToolbar } from './statistics-ui/toolbar'

const ResourceManagement = lazy(() => import('./ResourceManagement').then(module => ({default: module.ResourceManagement})))
const StatisticsChart = lazy(() => import('../components/StatisticsChart').then(module => ({default: module.StatisticsChart})))

/**
 * 统计分析页：按分类渲染指标卡、图表与明细表；编辑模式下支持卡片拖动、组合、隐藏等布局自定义，
 * 并提供分类数据 CSV 导出；库存分类可触发后端盘点任务。
 */
export function Statistics() {
  const {ui, notify} = useApp()
  const {instance = ''} = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const management = searchParams.get('view') === 'management'
  const {category, days, month, period, researchSeries, lootTask, zeroBase, setCategory, setDays, setMonth, setPeriod, setResearchSeries, setLootTask, setZeroBase} = useStatisticsPrefs()
  const {revision, setRevision, data, refreshing, startingStorage, storageError, chainData, chainError, rawTableOf, refresh, runStorageStatistics, download, reportOf} = useStatisticsData({instance, category})
  const {editMode, customized, layout, applyLayout, toggleEditMode, resetLayout, expandedChart, toggleExpanded} = useStatisticsEdit({ui, notify})
  const [draggingKey, setDraggingKey] = useState<string | null>(null)
  const [dropTarget, setDropTarget] = useState<{key: string, after: boolean} | null>(null)
  const connection = useConnection()

  const {spaceOf, spaceKeysOf, pageView, spaceView, showKey, hideKey, moveCard, junctionButton} = createCardModel({layout, chainData, editMode, ui, applyLayout})

  const pageIds = orderPages(layout)
  const singleView = layout.singleView
  const singleViewToggle = editMode ? <Button type="button" variant={singleView ? 'default' : 'outline'} size="sm" aria-pressed={singleView} aria-label={ui('stats.mergePages')} title={ui('stats.mergePages')} onClick={() => applyLayout({...layout, singleView: !singleView})}>{ui('stats.mergePages')}</Button> : undefined
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
      const nextCategory = rest[0]
      if (nextCategory) setCategory(nextCategory)
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
    const targetPage = layout.pages[to]?.[0]
    if (!targetPage) return
    const next = movePageBeside(layout, page, targetPage, delta > 0)
    if (next !== layout) applyLayout(next)
  }

  const {actions, rangeControls, hints, categoryControl, categoryPicker, tableSettings} = createToolbar({ui, category, days, month, period, researchSeries, lootTask, data, setDays, setMonth, setPeriod, setResearchSeries, setLootTask, connection, startingStorage, refreshing, runStorageStatistics, refresh, download, editMode, toggleEditMode, layout, applyLayout, management, selectPage, navigationEntries, chainOf, singleViewToggle, togglePage, movePageBy})

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

  const cardContext = {ui, layout, editMode, dropTarget, draggingKey, setDraggingKey, applyLayout, spaceKeysOf, showKey, moveCard, hideKey, junctionButton, expandedChart, toggleExpanded, zeroBase, setZeroBase, rawTableOf, tableSettings, StatisticsChart}
  const content = <>
    <div className="statistics-toolbar-row">
      {categoryControl}
      {categoryPicker}
      {/* 动作按钮贴行尾，与左侧分类切换分居两端 */}
      {!management && <ActionGroup className="ml-auto">{actions}</ActionGroup>}
    </div>
    {!management && <div className="statistics-controls period-controls">{rangeControls}{hints}</div>}
    {editMode && !management && <StatisticsEditConsole customized={customized} pages={fixedPageOrder.map(id => ({id, label: ui(categories[id]), enabled: isPageEnabled(layout, id)}))} onTogglePage={id => togglePage(id, !isPageEnabled(layout, id))} onReset={resetLayout}>
      {/* 顺序控件：一次挪一格，组合链整体挪动。 */}
      <div className="statistics-page-order">
        {pageEntries.map(([id, label]) => {
          const at = layout.pages.findIndex(chain => chain.includes(id))
          return (
            <span className="statistics-page-order-item" key={id}>
              <button type="button" aria-label={ui('stats.moveEarlier', {label: ui(label)})} disabled={at <= 0} onClick={() => movePageBy(id, -1)}>◀</button>
              <span className="statistics-page-order-label">{ui(label)}</span>
              <button type="button" aria-label={ui('stats.moveLater', {label: ui(label)})} disabled={at < 0 || at >= layout.pages.length - 1} onClick={() => movePageBy(id, 1)}>▶</button>
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
      {(singleView ? [spaceOf(category)] : isPageEnabled(layout, category) ? [chainOf(category)] : []).map(space => {
        if (!space.length) return null
        const head = space[0]
        const view = spaceView(space)
        const error = space.map(page => chainError[page]).find(Boolean) ?? ''
        const ready = space.every(page => chainData[page] !== undefined)
        /* 每张卡按所属页自己的视图渲染：卡片形态由该页的数据决定。 */
        const draw = (key: string, next?: string) => {
          const page = key.slice(0, key.indexOf(':')) as Category
          const report = chainData[page]
          return report ? renderCard(cardContext, page, pageView(page, report), report, key, view.ordered.indexOf(key), next) : null
        }
        return <Fragment key={head}>
          {space.map(page => <CategorySection key={page} params={{instance, category: page, days, month, period, researchSeries, lootTask, includeSeries: pageNeedsSeries(layout, page)}} revision={revision}
            onState={state => reportOf(page, state.data, state.error)} render={() => null}/>)}
          <section className="statistics-page-section">
            {error ? <ErrorBox message={error} retry={() => setRevision(value => value + 1)}/>
              : !ready ? <Loading/>
                : <div className={`statistics-sections${editMode ? ' is-editing' : ''}`}>
                  {view.runs.map(run => {
                    const first = run.keys[0]
                    if (!first) return null
                    return run.keys.length > 1
                      ? <div className="stat-card-chain" key={first}>{run.keys.map(key => draw(key, view.visible[view.visible.indexOf(key) + 1]))}</div>
                      : draw(first, view.visible[view.visible.indexOf(first) + 1])
                  })}
                </div>}
          </section>
        </Fragment>
      })}
    </div>
    </>}
  </>

  // 现代版式：整页只放统计内容（不放调度器与任务计划），页名由顶栏居中显示。
  return <>
    <div className="statistics-modern">
      <h1 className="modern-sr-title">{ui('nav.statistics')}</h1>
      {content}
    </div>
  </>
}
