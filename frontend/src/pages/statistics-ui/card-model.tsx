/**
 * 从 Statistics.tsx 原 300-360、369、423-441、488-492 行提取，纯搬迁未改动。
 * 卡片视图模型：卡片键/组合链/顺序计算与连接、隐藏、移位等布局操作。
 */
import type {ReactNode} from 'react'
import {ChevronDown, Plus} from 'lucide-react'
import {cardKey, cardSpace, foldCard, hideCard, isCardFolded, isCardHidden, isLinked, isPageEnabled, linkChains, orderCards, orderPages, placeCard, readChains, rechain, showCard, splitChains, unfoldCard} from '../../app/statisticsLayout'
import type {StatisticsLayout} from '../../app/statisticsLayout'
import type {UiKey, UiTranslator} from '../../i18n'
import type { StatisticsReport } from '../../api/types'
import type {Category} from './shared'

/* 单页卡片视图的结构化类型：与 pageView 返回值逐字段对应，供其他域文件以独立类型引用。 */
export interface PageView {
  cardClass: (key: string) => string
  foldControl: (key: string, place?: 'corner' | 'center', foldLabel?: UiKey, unfoldLabel?: UiKey) => ReactNode
  metricsKey: string
  chartKey: string
  plotKey: string
  rawKey: string
  tableKeys: string[]
  cardKeys: string[]
  chains: string[][]
  spaceOrder: string[]
  visibleKeys: string[]
}

export function createCardModel({layout, chainData, editMode, ui, applyLayout}: {
  layout: StatisticsLayout
  chainData: Partial<Record<Category, StatisticsReport>>
  editMode: boolean
  ui: UiTranslator
  applyLayout: (next: StatisticsLayout) => void
}) {
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
    const defaultChains = report?.series.length ? [[chartKey, rawKey]] : []
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

  // 卡片空间视图：一个空间（组合页或单页视图）渲染成一段，链与顺序在空间全量上算，
  // 跨页的链因此落进同一个容器。
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

  const applyChains = (page: Category, view: PageView, next: StatisticsLayout, moved?: string) => applyLayout({...next, cards: {...next.cards, [cardSpace(layout, page)]: rechain(view.chains, orderCards(next, page, spaceKeysOf(page)).filter(item => !isCardHidden(next, item)), moved)}})
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

  /* 连接符落在承载那段空白的元素上：可见卡后面紧邻隐藏卡时由占位条承接，纵向居中于两侧卡片之间。 */
  const junctionButton = (page: Category, view: PageView, left: string, right: string) => {
    const linked = isLinked(view.chains, left, right)
    return <button type="button" className={`stat-card-junction${linked ? ' is-linked' : ''}`} aria-label={ui(linked ? 'stats.unlinkCards' : 'stats.linkCards')} title={ui(linked ? 'stats.unlinkCards' : 'stats.linkCards')} onClick={() => linked ? splitCards(page, view, left, right) : linkCards(page, view, left, right)}>{linked ? <span className="stat-card-bar"/> : <Plus size={15}/>}</button>
  }

  return {pageCards, spaceOf, spaceKeysOf, spaceVisibleOf, keyListFor, pageView, spaceView, applyChains, linkCards, splitCards, hideKey, showKey, moveCard, junctionButton}
}

