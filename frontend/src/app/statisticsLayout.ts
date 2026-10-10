/**
 * @fileoverview 统计页布局文档、卡片与页面排序、组合链及折叠状态管理。
 */

import { VALID_CATEGORIES, type StatisticsCategory } from './statisticsPrefs'

export type PageId = StatisticsCategory

/** 卡片顺序、组合链与隐藏名单共用的落盘键：平时是链首页面，单页视图下是全部启用页面共用的一个键。 */
export type SpaceKey = string

export interface StatisticsLayout {
  version: 1
  pages: PageId[][]
  slots: PageId[][]
  enabled: Record<PageId, boolean>
  singleView: boolean
  cards: Partial<Record<SpaceKey, string[][]>>
  order: Partial<Record<SpaceKey, string[]>>
  hidden: Partial<Record<SpaceKey, string[]>>
  folded: string[]
  /** 图表表头用紧凑排列的页面：一行一个资源。 */
  compactChart: PageId[]
  /** 收获用表格式呈现的页面：指标横向排成一行。 */
  metricsTable: PageId[]
  /** 非编辑模式下不展示表头选取器的页面。 */
  hidePicker: PageId[]
  /** 行动力曲线按涨跌染色（叠涨视图）的页面。 */
  stackedRise: PageId[]
  /** 表格卡的显示设置，按卡键记（一表一键）。 */
  tables: Record<string, TableDisplay>
  /** 被点掉曲线的资源键，按页记：表头保留该资源，只是不画进图里。 */
  filteredSeries: Partial<Record<PageId, string[]>>
}

/** 表格卡每页行数的默认值，也是未设置时的取值。 */
export const DEFAULT_TABLE_ROWS = 25

/** 单张表格的显示设置：每页行数（0 = 全部）、数值补图标、只留内容行。 */
export type TableDisplay = {rows?: number; icons?: boolean; plain?: boolean}

export const LAYOUT_KEY = 'azurpilot.statistics.layout'
export const EDIT_MODE_KEY = 'azurpilot.statistics.edit-mode'

const PAGE_IDS = VALID_CATEGORIES

function isPageId(value: unknown): value is PageId {
  return typeof value === 'string' && (PAGE_IDS as readonly string[]).includes(value)
}

function isCardKey(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}

export function defaultStatisticsLayout(): StatisticsLayout {
  const enabled: Partial<Record<PageId, boolean>> = {}
  for (const id of PAGE_IDS) enabled[id] = true
  return {
    version: 1,
    pages: PAGE_IDS.map(id => [id]),
    slots: [],
    enabled: enabled as Record<PageId, boolean>,
    singleView: false,
    cards: {},
    order: {},
    hidden: {},
    folded: [],
    compactChart: [],
    metricsTable: [],
    hidePicker: [],
    stackedRise: [],
    tables: {},
    filteredSeries: {},
  }
}

export const DEFAULT_STATISTICS_LAYOUT: StatisticsLayout = defaultStatisticsLayout()

/** 键在整份文档里只保留第一次出现：重复项丢弃，空链丢弃。 */
function normalizeChains<T extends string>(value: unknown, accept: (item: unknown) => item is T): T[][] {
  if (!Array.isArray(value)) return []
  const seen = new Set<string>()
  const chains: T[][] = []
  for (const chain of value) {
    if (!Array.isArray(chain)) continue
    const keys: T[] = []
    for (const item of chain) {
      if (!accept(item) || seen.has(item)) continue
      seen.add(item)
      keys.push(item)
    }
    if (keys.length) chains.push(keys)
  }
  return chains
}

function normalizeKeyList(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined
  const seen = new Set<string>()
  const keys: string[] = []
  for (const item of value) {
    if (!isCardKey(item) || seen.has(item)) continue
    seen.add(item)
    keys.push(item)
  }
  return keys.length ? keys : undefined
}

function normalizePages(value: unknown): PageId[][] {
  const pages = normalizeChains(value, isPageId)
  const present = new Set(pages.flat())
  for (const id of PAGE_IDS) {
    if (!present.has(id)) pages.push([id])
  }
  return pages
}

function normalizeEnabled(value: unknown): Record<PageId, boolean> {
  const source = value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
  const enabled: Partial<Record<PageId, boolean>> = {}
  for (const id of PAGE_IDS) {
    enabled[id] = typeof source[id] === 'boolean' ? (source[id] as boolean) : true
  }
  return enabled as Record<PageId, boolean>
}

function isSpaceKey(key: string): boolean {
  return isPageId(key) || key === SINGLE_VIEW_SPACE
}

function normalizeCards(value: unknown): Partial<Record<PageId, string[][]>> {
  if (!value || typeof value !== 'object') return {}
  const cards: Partial<Record<SpaceKey, string[][]>> = {}
  for (const [key, chains] of Object.entries(value as Record<string, unknown>)) {
    if (!isSpaceKey(key)) continue
    cards[key] = normalizeChains(chains, isCardKey)
  }
  return cards
}

function normalizeHidden(value: unknown): Partial<Record<PageId, string[]>> {
  if (!value || typeof value !== 'object') return {}
  const hidden: Partial<Record<SpaceKey, string[]>> = {}
  for (const [key, keys] of Object.entries(value as Record<string, unknown>)) {
    if (!isSpaceKey(key)) continue
    const normalized = normalizeKeyList(keys)
    if (normalized) hidden[key] = normalized
  }
  return hidden
}

function normalizeOrder(value: unknown): Partial<Record<PageId, string[]>> {
  if (!value || typeof value !== 'object') return {}
  const order: Partial<Record<SpaceKey, string[]>> = {}
  for (const [key, keys] of Object.entries(value as Record<string, unknown>)) {
    if (!isSpaceKey(key)) continue
    const normalized = normalizeKeyList(keys)
    if (normalized) order[key] = normalized
  }
  return order
}

/** 逐表校验显示设置：行数取非负整数，布尔项只认布尔值，一项不合法只丢该项。 */
function normalizeTables(value: unknown): Record<string, TableDisplay> {
  if (!value || typeof value !== 'object') return {}
  const tables: Record<string, TableDisplay> = {}
  for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
    if (!key || !raw || typeof raw !== 'object') continue
    const source = raw as Record<string, unknown>
    const entry: TableDisplay = {}
    if (typeof source.rows === 'number' && Number.isFinite(source.rows) && source.rows >= 0) entry.rows = Math.floor(source.rows)
    if (typeof source.icons === 'boolean') entry.icons = source.icons
    if (typeof source.plain === 'boolean') entry.plain = source.plain
    if (Object.keys(entry).length) tables[key] = entry
  }
  return tables
}

/** 逐页校验被点掉的曲线键；一项不合法只丢该项。 */
function normalizeFilteredSeries(value: unknown): Partial<Record<PageId, string[]>> {
  if (!value || typeof value !== 'object') return {}
  const filtered: Partial<Record<PageId, string[]>> = {}
  for (const [page, keys] of Object.entries(value as Record<string, unknown>)) {
    if (!isPageId(page)) continue
    const normalized = normalizeKeyList(keys)
    if (normalized) filtered[page] = normalized
  }
  return filtered
}

function normalizeLayout(value: unknown): StatisticsLayout {
  if (!value || typeof value !== 'object') return defaultStatisticsLayout()
  const source = value as Record<string, unknown>
  if (source.version !== 1) return defaultStatisticsLayout()
  return {
    version: 1,
    pages: normalizePages(source.pages),
    slots: normalizeChains(source.slots, isPageId),
    enabled: normalizeEnabled(source.enabled),
    singleView: typeof source.singleView === 'boolean' ? source.singleView : false,
    cards: normalizeCards(source.cards),
    order: normalizeOrder(source.order),
    hidden: normalizeHidden(source.hidden),
    folded: normalizeKeyList(source.folded) ?? [],
    compactChart: (normalizeKeyList(source.compactChart) ?? []).filter(isPageId),
    metricsTable: (normalizeKeyList(source.metricsTable) ?? []).filter(isPageId),
    hidePicker: (normalizeKeyList(source.hidePicker) ?? []).filter(isPageId),
    stackedRise: (normalizeKeyList(source.stackedRise) ?? []).filter(isPageId),
    tables: normalizeTables(source.tables),
    filteredSeries: normalizeFilteredSeries(source.filteredSeries),
  }
}

/** 卡片键带页面前缀，跨页唯一；折叠状态以它为准。 */
export function cardKey(page: PageId, local: string): string {
  return `${page}:${local}`
}

/** 图表表头是否用紧凑排列：一行一个资源，列对齐但不画表格。 */
export function isChartCompact(layout: StatisticsLayout, page: PageId): boolean {
  return layout.compactChart.includes(page)
}

/** 非编辑模式下是否不展示表头选取器；编辑模式始终展示，否则无从改选资源。 */
export function isPickerHidden(layout: StatisticsLayout, page: PageId): boolean {
  return layout.hidePicker.includes(page)
}

/** 逐页记录非编辑模式是否隐藏选取器。 */
export function setPickerHidden(layout: StatisticsLayout, page: PageId, hidden: boolean): StatisticsLayout {
  const next = hidden ? [...new Set([...layout.hidePicker, page])] : layout.hidePicker.filter(item => item !== page)
  return {...layout, hidePicker: next}
}

/** 单张表格交给组件用的三项设置，未设置时取默认值。 */
export function tableDisplay(layout: StatisticsLayout, key: string): {rows: number; icons: boolean; plain: boolean} {
  const entry = layout.tables[key]
  return {rows: entry?.rows ?? DEFAULT_TABLE_ROWS, icons: entry?.icons ?? false, plain: entry?.plain ?? false}
}

/** 写入单张表格的显示设置；传 undefined 的项表示不改。 */
export function setTableDisplay(layout: StatisticsLayout, key: string, patch: TableDisplay): StatisticsLayout {
  const next = {...layout.tables[key], ...patch}
  for (const [field, value] of Object.entries(next) as Array<[keyof TableDisplay, TableDisplay[keyof TableDisplay]]>) {
    if (value === undefined) delete next[field]
  }
  const tables = {...layout.tables}
  if (Object.keys(next).length) tables[key] = next
  else delete tables[key]
  return {...layout, tables}
}

/** 该页行动力曲线是否按涨跌染色。 */
export function isStackedRise(layout: StatisticsLayout, page: PageId): boolean {
  return layout.stackedRise.includes(page)
}

/** 逐页切换行动力曲线的涨跌染色。 */
export function setStackedRise(layout: StatisticsLayout, page: PageId, on: boolean): StatisticsLayout {
  const next = on ? [...new Set([...layout.stackedRise, page])] : layout.stackedRise.filter(item => item !== page)
  return {...layout, stackedRise: next}
}

/** 该页某条曲线是否被点掉。 */
export function isSeriesFiltered(layout: StatisticsLayout, page: PageId, key: string): boolean {
  return (layout.filteredSeries[page] ?? []).includes(key)
}

/** 逐页切换某条曲线的显示与隐藏。 */
export function toggleSeriesFilter(layout: StatisticsLayout, page: PageId, key: string): StatisticsLayout {
  const current = layout.filteredSeries[page] ?? []
  const next = current.includes(key) ? current.filter(item => item !== key) : [...current, key]
  const filteredSeries = {...layout.filteredSeries}
  if (next.length) filteredSeries[page] = next
  else delete filteredSeries[page]
  return {...layout, filteredSeries}
}

/** 收获是否用表格式呈现：表头一行放指标名，表体一行放数值。 */
export function isMetricsTable(layout: StatisticsLayout, page: PageId): boolean {
  return layout.metricsTable.includes(page)
}

/** 逐页切换收获的呈现方式；只改收获这一块的数据排布，不动卡片容器本身。 */
export function setMetricsTable(layout: StatisticsLayout, page: PageId, table: boolean): StatisticsLayout {
  const next = table ? [...new Set([...layout.metricsTable, page])] : layout.metricsTable.filter(item => item !== page)
  return {...layout, metricsTable: next}
}

/** 逐页切换图表表头的排列方式；紧凑模式不影响该页其它显示状态。 */
export function setChartCompact(layout: StatisticsLayout, page: PageId, compact: boolean): StatisticsLayout {
  const next = compact ? [...new Set([...layout.compactChart, page])] : layout.compactChart.filter(item => item !== page)
  return {...layout, compactChart: next}
}

export function isCardFolded(layout: StatisticsLayout, key: string): boolean {
  return layout.folded.includes(key)
}

export function foldCard(layout: StatisticsLayout, key: string): StatisticsLayout {
  return isCardFolded(layout, key) ? layout : {...layout, folded: [...layout.folded, key]}
}

export function unfoldCard(layout: StatisticsLayout, key: string): StatisticsLayout {
  return isCardFolded(layout, key) ? {...layout, folded: layout.folded.filter(item => item !== key)} : layout
}

/** 单页视图把全部启用页面当成一条整链，链与顺序表都落在同一个键上；退出单页视图后这个键读不到，等于自动回滚。 */
export const SINGLE_VIEW_SPACE = 'single'

/** 卡片空间的键：组合链内的页面共用一套卡片顺序与连接，取链首页面。 */
export function cardSpace(layout: StatisticsLayout, page: PageId): string {
  if (layout.singleView) return SINGLE_VIEW_SPACE
  return layout.pages.find(chain => chain.includes(page))?.[0] ?? page
}

/** 按顺序表排列当前页的卡片键：表里没有的键保持原有相对次序，排在后面。 */
export function orderCards(layout: StatisticsLayout, page: PageId, keys: string[]): string[] {
  const order = layout.order[cardSpace(layout, page)]
  if (!order?.length) return keys
  const rank = new Map(order.map((key, index) => [key, index]))
  return [...keys].sort((a, b) => (rank.get(a) ?? order.length) - (rank.get(b) ?? order.length))
}

/** 卡片是否被隐藏：隐藏名单按页存放，键里带页号。 */
/** 该页的图表与原始记录是否至少有一张可见：两张都隐藏时后端不必查询序列数据。 */
export function pageNeedsSeries(layout: StatisticsLayout, page: PageId): boolean {
  return !isCardHidden(layout, cardKey(page, 'chart')) || !isCardHidden(layout, cardKey(page, 'raw'))
}

export function isCardHidden(layout: StatisticsLayout, key: string): boolean {
  const page = pageOfKey(key)
  return Boolean(page && layout.hidden[cardSpace(layout, page)]?.includes(key))
}

/** 隐藏卡片：加入卡片空间的隐藏名单，并把所在链在此处断开，左右两张卡也不再相连。 */
export function hideCard(layout: StatisticsLayout, key: string): StatisticsLayout {
  const page = pageOfKey(key)
  if (!page || isCardHidden(layout, key)) return layout
  const space = cardSpace(layout, page)
  const chains = layout.cards[space]
  const cards = chains
    ? {...layout.cards, [space]: chains.flatMap(chain => {
      const at = chain.indexOf(key)
      return at < 0 ? [chain] : [chain.slice(0, at), chain.slice(at + 1)].filter(part => part.length)
    })}
    : layout.cards
  return {...layout, cards, hidden: {...layout.hidden, [space]: [...(layout.hidden[space] ?? []), key]}}
}

/** 取消隐藏：从当前页的隐藏名单里移除。 */
export function showCard(layout: StatisticsLayout, key: string): StatisticsLayout {
  const page = pageOfKey(key)
  const space = page ? cardSpace(layout, page) : undefined
  const keys = space ? layout.hidden[space] : undefined
  if (!space || !keys?.includes(key)) return layout
  const rest = keys.filter(item => item !== key)
  const hidden = {...layout.hidden}
  if (rest.length) hidden[space] = rest
  else delete hidden[space]
  return {...layout, hidden}
}

function pageOfKey(key: string): PageId | undefined {
  const page = key.slice(0, key.indexOf(':'))
  return isPageId(page) ? page : undefined
}

/** 当前页的卡片链：用户还没动过时用默认链（紧凑外壳下图表与其表格本就连在一起）。 */
export function readChains(layout: StatisticsLayout, page: PageId, fallback: string[][] = []): string[][] {
  const stored = layout.cards[cardSpace(layout, page)]
  return stored ?? fallback
}

/** 两张卡片是否同链，即是否处在同一容器里。 */
export function isLinked(chains: string[][], left: string, right: string): boolean {
  return chains.some(chain => chain.includes(left) && chain.includes(right))
}

/** 接上两张相邻卡：两链合并为一，已经同链时原样返回。 */
export function linkChains(chains: string[][], left: string, right: string): string[][] {
  if (isLinked(chains, left, right)) return chains
  const merged = [...chainOf(chains, left), ...chainOf(chains, right)]
  return [...chains.filter(chain => !chain.includes(left) && !chain.includes(right)), merged]
}

/** 断开这两张相邻卡之间的连接：按当前顺序把它们所在的链切成两段，其余成员保持相连。 */
export function splitChains(chains: string[][], orderedKeys: string[], left: string, right: string): string[][] {
  const chain = chains.find(item => item.includes(left) && item.includes(right))
  if (!chain) return chains
  const members = orderedKeys.filter(key => chain.includes(key))
  const cut = members.indexOf(left) + 1
  if (members.indexOf(right) !== cut) return chains
  const head = members.slice(0, cut)
  const tail = members.slice(cut)
  return [...chains.filter(item => item !== chain), ...[head, tail].filter(part => part.length)]
}

/** 修正链：被移动的卡片与原来的伙伴断开；落到两张同链卡之间时并入该链；其余只保留前后相邻的成员。 */
export function rechain(chains: string[][], orderedKeys: string[], moved?: string): string[][] {
  const source = moved ? chains.map(chain => chain.filter(key => key !== moved)) : chains
  const rebuilt: string[][] = []
  for (const chain of source) {
    const merged: string[] = []
    for (let index = 0; index < orderedKeys.length; index += 1) {
      const key = orderedKeys[index]
      if (chain.includes(key)) { merged.push(key); continue }
      const before = orderedKeys[index - 1]
      const after = orderedKeys[index + 1]
      if (moved && before && after && chain.includes(before) && chain.includes(after)) merged.push(key)
    }
    let run: string[] = []
    for (const key of orderedKeys) {
      if (merged.includes(key)) { run.push(key); continue }
      if (run.length) { rebuilt.push(run); run = [] }
    }
    if (run.length) rebuilt.push(run)
  }
  return rebuilt.filter(chain => chain.length > 1)
}

function chainOf(chains: string[][], key: string): string[] {
  return chains.find(chain => chain.includes(key)) ?? [key]
}

/** 把卡片移到当前顺序里的新位置；越界或原地不动时返回原对象。 */
export function placeCard(layout: StatisticsLayout, page: PageId, keys: string[], key: string, index: number): StatisticsLayout {
  const current = orderCards(layout, page, keys)
  const from = current.indexOf(key)
  const to = Math.max(0, Math.min(current.length - 1, index))
  if (from < 0 || from === to) return layout
  const next = [...current]
  next.splice(from, 1)
  next.splice(to, 0, key)
  return {...layout, order: {...layout.order, [cardSpace(layout, page)]: next}}
}

export function readStatisticsLayout(): StatisticsLayout {
  try {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(LAYOUT_KEY) : null
    if (!raw) return defaultStatisticsLayout()
    return normalizeLayout(JSON.parse(raw) as unknown)
  } catch {
    /* 内容损坏或存储不可用时按原版布局。 */
  }
  return defaultStatisticsLayout()
}

export function writeStatisticsLayout(layout: StatisticsLayout): void {
  try {
    if (typeof localStorage === 'undefined') return
    localStorage.setItem(LAYOUT_KEY, JSON.stringify(normalizeLayout(layout)))
  } catch {
    /* 存储不可用时本次会话内仍生效。 */
  }
}

/** 存储里有布局文档即为已自定义；原版布局不留键，一键还原后回到未自定义。 */
export function hasStatisticsLayout(): boolean {
  try {
    return typeof localStorage !== 'undefined' && localStorage.getItem(LAYOUT_KEY) !== null
  } catch {
    return false
  }
}

export function resetStatisticsLayout(): void {
  try {
    if (typeof localStorage !== 'undefined') localStorage.removeItem(LAYOUT_KEY)
  } catch {
    /* 存储不可用时没有需要清理的内容。 */
  }
}

export function readStatisticsEditMode(): boolean {
  try {
    return typeof localStorage !== 'undefined' && localStorage.getItem(EDIT_MODE_KEY) === '1'
  } catch {
    return false
  }
}

export function writeStatisticsEditMode(enabled: boolean): void {
  try {
    if (typeof localStorage === 'undefined') return
    if (enabled) localStorage.setItem(EDIT_MODE_KEY, '1')
    else localStorage.removeItem(EDIT_MODE_KEY)
  } catch {
    /* 存储不可用时仅当前会话生效。 */
  }
}

/** 页面入口的显示顺序：链按存档顺序展开。 */
export function orderPages(layout: StatisticsLayout): PageId[] {
  return layout.pages.flat()
}

/** 页面是否出现在入口条上；禁用只影响入口，卡片布局原样保留。 */
export function isPageEnabled(layout: StatisticsLayout, page: PageId): boolean {
  return layout.enabled[page] !== false
}

export function setPageEnabled(layout: StatisticsLayout, page: PageId, enabled: boolean): StatisticsLayout {
  return {...layout, enabled: {...layout.enabled, [page]: enabled}}
}
/** 把该页所在的链移到目标页之前或之后，越界时贴到首尾。 */
export function movePageBeside(layout: StatisticsLayout, page: PageId, target: PageId, after: boolean): StatisticsLayout {
  const chain = layout.pages.find(item => item.includes(page))
  const anchor = layout.pages.find(item => item.includes(target))
  if (!chain || !anchor || chain === anchor) return layout
  const rest = layout.pages.filter(item => item !== chain)
  rest.splice(rest.indexOf(anchor) + (after ? 1 : 0), 0, chain)
  return {...layout, pages: rest}
}

/** 槽位行是组合的唯一来源：满两页的行合成一条链，其余页面各成一行并保持原有先后。 */
export function applySlots(layout: StatisticsLayout, slots: PageId[][]): StatisticsLayout {
  const rows = slots.filter(row => row.length >= 2)
  const rowOf = (page: PageId) => rows.find(row => row.includes(page))
  const placed = new Set<PageId[]>()
  const pages: PageId[][] = []
  for (const page of layout.pages.flat()) {
    const row = rowOf(page)
    if (!row) {
      pages.push([page])
      continue
    }
    if (placed.has(row)) continue
    placed.add(row)
    pages.push([...row])
  }
  for (const row of rows) if (!placed.has(row)) pages.push([...row])
  return {...layout, slots, pages}
}
