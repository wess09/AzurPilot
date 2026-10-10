import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { VALID_CATEGORIES } from './statisticsPrefs'
import type {StatisticsLayout} from './statisticsLayout'
import {DEFAULT_TABLE_ROWS, readStatisticsLayout, setTableDisplay, tableDisplay, writeStatisticsLayout} from './statisticsLayout'
import {cardKey, DEFAULT_STATISTICS_LAYOUT, defaultStatisticsLayout, EDIT_MODE_KEY, hideCard, isCardHidden, isChartCompact, isLinked, isMetricsTable, isPickerHidden, isSeriesFiltered, isStackedRise, LAYOUT_KEY, linkChains, pageNeedsSeries, readChains, rechain, setChartCompact, setMetricsTable, setPickerHidden, setStackedRise, showCard, splitChains, toggleSeriesFilter} from './statisticsLayout'

function memoryStorage() {
  const map = new Map<string, string>()
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => void map.set(key, value),
    removeItem: (key: string) => void map.delete(key),
  }
}

async function loadLayout() {
  vi.resetModules()
  vi.stubGlobal('localStorage', memoryStorage())
  return import('./statisticsLayout')
}

afterEach(() => vi.unstubAllGlobals())

describe('统计页布局文档持久化', () => {
  it('未存储时返回默认布局：每页各成一条链、全部启用、无卡片改动', async () => {
    const layout = await loadLayout()

    const loaded = layout.readStatisticsLayout()
    expect(loaded).toEqual(DEFAULT_STATISTICS_LAYOUT)
    expect(loaded.pages.every(chain => chain.length === 1)).toBe(true)
    expect(Object.values(loaded.enabled).every(Boolean)).toBe(true)
  })

  it('写入后重新加载能完整还原顺序、组合、禁用、隐藏与折叠', async () => {
    const first = await loadLayout()
    first.writeStatisticsLayout({
      ...DEFAULT_STATISTICS_LAYOUT,
      pages: [['opsi', 'loot'], ['resources'], ['action'], ['commission'], ['ships'], ['research']],
      enabled: { ...DEFAULT_STATISTICS_LAYOUT.enabled, commission: false },
      cards: { commission: [['委托收益明细', '委托结算记录']] },
      hidden: { commission: ['委托结算记录'] },
      folded: ['委托收益明细'],
    })
    expect(localStorage.getItem(LAYOUT_KEY)).toBeTruthy()

    vi.resetModules()
    const second = await import('./statisticsLayout')
    const loaded = second.readStatisticsLayout()
    expect(loaded.pages[0]).toEqual(['opsi', 'loot'])
    expect(loaded.enabled.commission).toBe(false)
    expect(loaded.cards.commission).toEqual([['委托收益明细', '委托结算记录']])
    expect(loaded.hidden.commission).toEqual(['委托结算记录'])
    expect(loaded.folded).toEqual(['委托收益明细'])
  })

  it('版本不符或整体损坏时回退默认布局', async () => {
    vi.resetModules()
    vi.stubGlobal('localStorage', memoryStorage())
    localStorage.setItem(LAYOUT_KEY, JSON.stringify({ version: 99, pages: [['opsi']], singleView: true }))

    const { readStatisticsLayout } = await import('./statisticsLayout')
    expect(readStatisticsLayout()).toEqual(DEFAULT_STATISTICS_LAYOUT)
  })

  it('版本正确但页面缺项时补回默认顺序，未知页面被丢弃且不出现重复', async () => {
    vi.resetModules()
    vi.stubGlobal('localStorage', memoryStorage())
    localStorage.setItem(
      LAYOUT_KEY,
      JSON.stringify({
        version: 1,
        pages: [['opsi', 'not_a_page'], ['opsi'], ['loot']],
        enabled: { opsi: false, not_a_page: true },
        singleView: 'yes',
        cards: { not_a_page: [['x']], commission: [['a'], ['a', 'b']] },
        hidden: { commission: 'nope' },
        folded: ['委托收益明细', 3, '委托收益明细'],
      }),
    )

    const { readStatisticsLayout } = await import('./statisticsLayout')
    const loaded = readStatisticsLayout()
    const flat = loaded.pages.flat()

    expect(flat).toContain('opsi')
    expect(flat).toContain('loot')
    expect(new Set(flat)).toEqual(new Set(VALID_CATEGORIES))
    expect(flat.length).toBe(new Set(flat).size)
    expect(loaded.pages[0]).toEqual(['opsi'])
    expect(loaded.pages[1]).toEqual(['loot'])
    expect(loaded.enabled.opsi).toBe(false)
    expect(loaded.enabled.resources).toBe(true)
    expect(loaded.singleView).toBe(false)
    expect(loaded.cards.commission).toEqual([['a'], ['b']])
    expect(Object.keys(loaded.cards)).not.toContain('not_a_page')
    expect(loaded.hidden.commission).toBeUndefined()
    expect(loaded.folded).toEqual(['委托收益明细'])
  })

  it('一键还原删除存储键并回到默认布局', async () => {
    const layout = await loadLayout()
    layout.writeStatisticsLayout({ ...DEFAULT_STATISTICS_LAYOUT, singleView: true })
    expect(localStorage.getItem(LAYOUT_KEY)).toBeTruthy()

    layout.resetStatisticsLayout()
    expect(localStorage.getItem(LAYOUT_KEY)).toBeNull()
    expect(layout.readStatisticsLayout()).toEqual(DEFAULT_STATISTICS_LAYOUT)
  })

  it('编辑模式默认关闭，开启后重新加载仍为开启，关闭后不留痕', async () => {
    const layout = await loadLayout()
    expect(layout.readStatisticsEditMode()).toBe(false)

    layout.writeStatisticsEditMode(true)
    vi.resetModules()
    const second = await import('./statisticsLayout')
    expect(second.readStatisticsEditMode()).toBe(true)

    second.writeStatisticsEditMode(false)
    expect(localStorage.getItem(EDIT_MODE_KEY)).toBeNull()
    expect(second.readStatisticsEditMode()).toBe(false)
  })
  it('折叠与展开只动目标卡片，且不改动传入的文档', async () => {
    const layout = await loadLayout()
    const key = layout.cardKey('commission', 'table:委托结算记录')
    const before = layout.readStatisticsLayout()

    const folded = layout.foldCard(before, key)
    expect(layout.isCardFolded(folded, key)).toBe(true)
    expect(before.folded).toEqual([])
    expect(layout.foldCard(folded, key)).toBe(folded)

    const unfolded = layout.unfoldCard(folded, key)
    expect(layout.isCardFolded(unfolded, key)).toBe(false)
    expect(folded.folded).toEqual([key])
  })

  it('按存储键判断布局是否被自定义过', async () => {
    const layout = await loadLayout()
    expect(layout.hasStatisticsLayout()).toBe(false)

    layout.writeStatisticsLayout({ ...DEFAULT_STATISTICS_LAYOUT, singleView: true })
    expect(layout.hasStatisticsLayout()).toBe(true)

    layout.resetStatisticsLayout()
    expect(layout.hasStatisticsLayout()).toBe(false)
  })
})


describe('统计页卡片顺序', () => {
  const page = 'commission' as const
  const keys = [cardKey(page, 'metrics'), cardKey(page, 'chart'), cardKey(page, 'table:委托明细')]

  it('按顺序表排列；表里没有的键保持原有相对次序并排在后面', async () => {
    const layout = await loadLayout()

    const ordered = layout.orderCards({ ...DEFAULT_STATISTICS_LAYOUT, order: { [page]: [cardKey(page, 'chart'), cardKey(page, 'metrics')] } }, page, keys)
    expect(ordered).toEqual([cardKey(page, 'chart'), cardKey(page, 'metrics'), cardKey(page, 'table:委托明细')])
    expect(layout.orderCards(DEFAULT_STATISTICS_LAYOUT, page, keys)).toEqual(keys)
  })

  it('移位写入顺序表；越界与原地不动返回原对象', async () => {
    const layout = await loadLayout()

    const moved = layout.placeCard(DEFAULT_STATISTICS_LAYOUT, page, keys, cardKey(page, 'metrics'), 2)
    expect(moved.order[page]).toEqual([cardKey(page, 'chart'), cardKey(page, 'table:委托明细'), cardKey(page, 'metrics')])
    expect(layout.placeCard(moved, page, keys, cardKey(page, 'metrics'), 2)).toBe(moved)
    expect(layout.placeCard(DEFAULT_STATISTICS_LAYOUT, page, keys, cardKey(page, 'metrics'), 99).order[page]).toEqual([cardKey(page, 'chart'), cardKey(page, 'table:委托明细'), cardKey(page, 'metrics')])
    expect(layout.placeCard(DEFAULT_STATISTICS_LAYOUT, page, keys, cardKey(page, 'ghost'), 0)).toBe(DEFAULT_STATISTICS_LAYOUT)
  })

  it('插入到同链两张之间时三者成链', async () => {
    const layout = await loadLayout()

    const next = layout.rechain([['resources:chart', 'resources:raw']], ['resources:chart', 'action:chart', 'resources:raw', 'action:raw'], 'action:chart')

    expect(next).toEqual([['resources:chart', 'action:chart', 'resources:raw']])
  })

  it('跨页组合时移位写入组键，而不是卡片自身所在页', async () => {
    const layout = await loadLayout()
    const [head, other] = VALID_CATEGORIES
    const base = {...DEFAULT_STATISTICS_LAYOUT, pages: [[head, other]]}
    const keys = [cardKey(head, 'chart'), cardKey(other, 'chart')]

    const moved = layout.placeCard(base, other, keys, cardKey(other, 'chart'), 0)

    expect(moved.order[head]).toEqual([cardKey(other, 'chart'), cardKey(head, 'chart')])
    expect(moved.order[other]).toBeUndefined()
  })

  it('顺序表随文档落盘并能读回', async () => {
    const first = await loadLayout()
    first.writeStatisticsLayout({ ...DEFAULT_STATISTICS_LAYOUT, order: { [page]: [cardKey(page, 'chart'), cardKey(page, 'metrics')] } })

    vi.resetModules()
    const second = await import('./statisticsLayout')
    expect(second.readStatisticsLayout().order[page]).toEqual([cardKey(page, 'chart'), cardKey(page, 'metrics')])
  })
})

describe('统计页卡片组合', () => {
  const chart = cardKey('commission', 'chart')
  const metrics = cardKey('commission', 'metrics')
  const first = cardKey('commission', 'table:委托收益明细')
  const second = cardKey('commission', 'table:委托结算记录')

  it('没动过时用默认链，动过以后以存储为准', () => {
    const empty = {...DEFAULT_STATISTICS_LAYOUT}
    expect(readChains(empty, 'commission', [[chart, first]])).toEqual([[chart, first]])
    const stored = {...empty, cards: {commission: [[chart], [first, second]]}}
    expect(readChains(stored, 'commission', [[chart, first]])).toEqual([[chart], [first, second]])
  })


  it('连接合并两链，已经同链时原样返回', () => {
    const linked = linkChains([[chart], [first]], chart, first)
    expect(linked).toEqual([[chart, first]])
    expect(isLinked(linked, chart, first)).toBe(true)
    const again = linkChains(linked, chart, first)
    expect(again).toBe(linked)
  })

  it('断开按当前顺序把链切成两段，其余成员保持相连', () => {
    const chains = [[chart, first, second]]
    expect(splitChains(chains, [chart, first, second], chart, first)).toEqual([[chart], [first, second]])
    expect(splitChains(chains, [chart, first, second], first, second)).toEqual([[chart, first], [second]])
    expect(splitChains(chains, [chart, metrics, first, second], metrics, first)).toBe(chains)
  })

  it('排序后链要连续：被移走的卡与伙伴断开，插进两卡之间则三者全链', () => {
    expect(rechain([[chart, first]], [chart, first, metrics])).toEqual([[chart, first]])
    expect(rechain([[chart, first]], [first, metrics, chart], chart)).toEqual([])
    expect(rechain([[first, second]], [first, chart, second], chart)).toEqual([[first, chart, second]])
    expect(rechain([[first, second]], [first, chart, second])).toEqual([])
  })
})

describe('统计页卡片隐藏', () => {
  const chart = cardKey('commission', 'chart')
  const first = cardKey('commission', 'table:委托收益明细')
  const other = cardKey('ships', 'chart')

  it('隐藏名单按页存放，同一张卡隐藏两次只记一条', () => {
    const once = hideCard(DEFAULT_STATISTICS_LAYOUT, first)
    expect(isCardHidden(once, first)).toBe(true)
    expect(isCardHidden(once, chart)).toBe(false)
    expect(hideCard(once, first)).toBe(once)
    expect(isCardHidden(once, other)).toBe(false)
  })

  it('取消隐藏后名单清空，页面不留空条目', () => {
    const once = hideCard(DEFAULT_STATISTICS_LAYOUT, first)
    const shown = showCard(once, first)
    expect(isCardHidden(shown, first)).toBe(false)
    expect(shown.hidden).toEqual({})
    expect(showCard(shown, first)).toBe(shown)
  })

  it('页号无效的键不改动文档', () => {
    expect(hideCard(DEFAULT_STATISTICS_LAYOUT, 'nonsense')).toBe(DEFAULT_STATISTICS_LAYOUT)
    expect(isCardHidden(DEFAULT_STATISTICS_LAYOUT, 'nonsense')).toBe(false)
  })

  it('图表与原始记录都隐藏时才不再需要序列数据', () => {
    const page = 'resources'
    expect(pageNeedsSeries(DEFAULT_STATISTICS_LAYOUT, page)).toBe(true)
    const chartHidden = hideCard(DEFAULT_STATISTICS_LAYOUT, cardKey(page, 'chart'))
    expect(pageNeedsSeries(chartHidden, page)).toBe(true)
    const bothHidden = hideCard(chartHidden, cardKey(page, 'raw'))
    expect(pageNeedsSeries(bothHidden, page)).toBe(false)
  })
})

describe('统计页链的存档语义', () => {
  it('存档里的空链表示「这个页面已设置过」，不能用默认链顶替', () => {
    const fallback = [[cardKey('commission', 'chart'), cardKey('commission', 'raw')]]
    const untouched: StatisticsLayout = {...DEFAULT_STATISTICS_LAYOUT}
    expect(readChains(untouched, 'commission', fallback)).toEqual(fallback)
    const cleared: StatisticsLayout = {...DEFAULT_STATISTICS_LAYOUT, cards: {commission: []}}
    expect(readChains(cleared, 'commission', fallback)).toEqual([])
  })
})

describe('槽位行与页面组合', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', memoryStorage())
  })

  it('满两页的行合成一条链，成员不再单独成行', async () => {
    const layout = await import('./statisticsLayout')
    const base = layout.defaultStatisticsLayout()
    const first = VALID_CATEGORIES[0]
    const second = VALID_CATEGORIES[1]
    const merged = layout.applySlots(base, [[first, second]])
    expect(merged.pages.filter(chain => chain.includes(first))).toEqual([[first, second]])
    expect(merged.pages.flat().length).toBe(VALID_CATEGORIES.length)
  })

  it('只有一页的行不算组合，页面仍单独成行', async () => {
    const layout = await import('./statisticsLayout')
    const base = layout.defaultStatisticsLayout()
    const only = VALID_CATEGORIES[2]
    const placed = layout.applySlots(base, [[only]])
    expect(placed.pages).toEqual(base.pages)
    expect(placed.slots).toEqual([[only]])
  })

  it('清空槽位行后页面回到各自单独成行', async () => {
    const layout = await import('./statisticsLayout')
    const base = layout.defaultStatisticsLayout()
    const merged = layout.applySlots(base, [[VALID_CATEGORIES[0], VALID_CATEGORIES[1]]])
    expect(layout.applySlots(merged, []).pages).toEqual(base.pages)
  })

  it('组合链落在首个成员原来的位置', async () => {
    const layout = await import('./statisticsLayout')
    const base = layout.defaultStatisticsLayout()
    const first = VALID_CATEGORIES[1]
    const later = VALID_CATEGORIES[3]
    const merged = layout.applySlots(base, [[first, later]])
    expect(merged.pages[1]).toEqual([first, later])
  })

  it('存档里只有一页的槽位行读回来仍是槽位行', async () => {
    const layout = await import('./statisticsLayout')
    const base = layout.defaultStatisticsLayout()
    localStorage.setItem(layout.LAYOUT_KEY, JSON.stringify({...base, slots: [[VALID_CATEGORIES[4]]]}))
    expect(layout.readStatisticsLayout().slots).toEqual([[VALID_CATEGORIES[4]]])
  })
})

/* 组合页里中间夹着隐藏卡时，两侧仍应能重新连接：隐藏只断开状态，不禁止连接。 */
describe('组合页与隐藏卡的连接', () => {
  const state = (): StatisticsLayout => ({
    ...DEFAULT_STATISTICS_LAYOUT,
    pages: [['resources', 'action'], ['opsi'], ['commission'], ['ships'], ['loot'], ['research']],
    cards: {resources: [['action:chart', 'action:raw']]},
    hidden: {resources: ['resources:raw']},
  })

  it('两侧卡片可以重新连上', () => {
    const layout = state()
    const before = readChains(layout, 'resources')
    expect(before).toEqual([['action:chart', 'action:raw']])
    const merged = linkChains(before, 'resources:chart', 'action:chart')
    const visible = ['resources:chart', 'action:chart', 'action:raw'].filter(key => !isCardHidden(layout, key))
    expect(rechain(merged, visible)).toEqual([['resources:chart', 'action:chart', 'action:raw']])
  })

  it('隐藏卡与相邻卡断开，另一侧成员保持相连', () => {
    const layout = {...state(), cards: {resources: [['resources:chart', 'resources:raw', 'action:chart', 'action:raw']]}, hidden: {}}
    const next = hideCard(layout, 'resources:raw')
    expect(next.cards.resources ?? []).toEqual([['resources:chart'], ['action:chart', 'action:raw']])
    expect(isLinked(next.cards.resources ?? [], 'resources:chart', 'action:chart')).toBe(false)
  })
})

describe('按页的显示方式开关', () => {
  it('图表紧凑排列与收获表格式都逐页记录，互不影响', () => {
    const base = defaultStatisticsLayout()
    const compact = setChartCompact(base, 'resources', true)
    expect(isChartCompact(compact, 'resources')).toBe(true)
    expect(isChartCompact(compact, 'action')).toBe(false)
    expect(isMetricsTable(compact, 'resources')).toBe(false)

    const table = setMetricsTable(compact, 'action', true)
    expect(isMetricsTable(table, 'action')).toBe(true)
    expect(isMetricsTable(table, 'resources')).toBe(false)
    expect(isChartCompact(table, 'resources')).toBe(true)

    expect(isMetricsTable(setMetricsTable(table, 'action', false), 'action')).toBe(false)
    expect(isStackedRise(setStackedRise(table, 'resources', true), 'resources')).toBe(true)
    expect(isStackedRise(setStackedRise(table, 'resources', true), 'action')).toBe(false)
    expect(isStackedRise(setStackedRise(table, 'resources', false), 'resources')).toBe(false)
    expect(isChartCompact(setChartCompact(table, 'resources', false), 'resources')).toBe(false)
  })
})

describe('选取器显隐与曲线筛选', () => {
  it('选取器显隐按页记录，筛选键可反复切换', () => {
    const base = defaultStatisticsLayout()
    const hidden = setPickerHidden(base, 'resources', true)
    expect(isPickerHidden(hidden, 'resources')).toBe(true)
    expect(isPickerHidden(hidden, 'action')).toBe(false)
    expect(isPickerHidden(setPickerHidden(hidden, 'resources', false), 'resources')).toBe(false)

    const off = toggleSeriesFilter(base, 'resources', 'oil')
    expect(isSeriesFiltered(off, 'resources', 'oil')).toBe(true)
    expect(isSeriesFiltered(off, 'action', 'oil')).toBe(false)
    const on = toggleSeriesFilter(off, 'resources', 'oil')
    expect(isSeriesFiltered(on, 'resources', 'oil')).toBe(false)
    expect(on.filteredSeries.resources).toBeUndefined()
  })
})

describe('表格显示设置（功能6/7/8）', () => {
  it('未设置时取默认行数，两个开关都关', () => {
    expect(tableDisplay(defaultStatisticsLayout(), 'action:raw')).toEqual({rows: DEFAULT_TABLE_ROWS, icons: false, plain: false})
  })

  it('一表一份设置，互不影响', () => {
    let layout = setTableDisplay(defaultStatisticsLayout(), 'action:raw', {rows: 5, icons: true})
    layout = setTableDisplay(layout, 'commission:table:委托收益', {plain: true})
    expect(tableDisplay(layout, 'action:raw')).toEqual({rows: 5, icons: true, plain: false})
    expect(tableDisplay(layout, 'commission:table:委托收益')).toEqual({rows: DEFAULT_TABLE_ROWS, icons: false, plain: true})
  })

  it('行数 0 与关闭开关都会如实落盘', () => {
    let layout = setTableDisplay(defaultStatisticsLayout(), 'action:raw', {rows: 0})
    expect(tableDisplay(layout, 'action:raw').rows).toBe(0)
    layout = setTableDisplay(layout, 'action:raw', {rows: DEFAULT_TABLE_ROWS})
    expect(tableDisplay(layout, 'action:raw').rows).toBe(DEFAULT_TABLE_ROWS)
    writeStatisticsLayout(layout)
    expect(tableDisplay(readStatisticsLayout(), 'action:raw')).toEqual({rows: DEFAULT_TABLE_ROWS, icons: false, plain: false})
  })
})
