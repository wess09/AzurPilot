/**
 * @fileoverview 统计页外观偏好、时间跨度、图表类型与指标筛选持久化。
 */

export type StatisticsCategory = 'resources' | 'action' | 'opsi' | 'commission' | 'ships' | 'loot' | 'research' | 'storage'
export type ChartMode = 'line' | 'candlestick'
export type ChartAxisMode = 'separate' | 'unified'
type CommissionPeriod = 'day' | 'week' | 'month'

/**
 * 统计页外观与交互偏好：统计分类、时间跨度、图表类型、采样粒度和选中的指标。
 *
 * 与其它界面偏好一致：关掉再打开接着上次的样子，直到用户自己调整。
 * 只存本浏览器，不区分实例。
 */
interface StatisticsPrefs {
  category: StatisticsCategory
  days: number
  period: CommissionPeriod
  /** 科研页面的视图：'1'~'9' 是各期，'consumable' 是心智/物资 */
  researchSelect: string
  /** 大世界掉落页的任务筛选：'' 是全部大世界任务，其余是任务标识（opsi_xxx） */
  lootTask: string
  chartMode: ChartMode
  chartAxisMode: ChartAxisMode
  /** 纵轴起始值固定为 0，缩放后不跟着可见范围浮动 */
  chartZeroBase: boolean
  bucket: number
  /** 图表与原始记录卡共用的时间范围，空表示不限 */
  rangeFrom: string
  rangeTo: string
  selectedKeys: Record<string, string[]>
}

/** 统计偏好所在 localStorage 的键；测试用它读写原始存储值。 */
export const PREFS_KEY = 'azurpilot.statistics'

/** 合法分类全集；statisticsLayout 以它的顺序决定统计页的分页顺序。 */
export const VALID_CATEGORIES: readonly StatisticsCategory[] = ['resources', 'action', 'opsi', 'commission', 'ships', 'loot', 'research', 'storage']
const VALID_DAYS: readonly number[] = [1, 7, 30, 90, 365]
const VALID_PERIODS: readonly CommissionPeriod[] = ['day', 'week', 'month']
const VALID_BUCKETS: readonly number[] = [0, 5, 60, 1440]
const VALID_CHART_MODES: readonly ChartMode[] = ['line', 'candlestick']
const VALID_AXIS_MODES: readonly ChartAxisMode[] = ['separate', 'unified']
const VALID_RESEARCH_SELECTS: readonly string[] = ['1', '2', '3', '4', '5', '6', '7', '8', '9', 'consumable']
/* 任务标识由后端给（opsi_xxx），这里只校验形状；下架的任务在页面里自然没有记录 */
const LOOT_TASK_PATTERN = /^[a-z][a-z0-9_]{0,40}$/

/** 默认偏好：无存储、存储损坏或字段非法时的回落值。 */
export const DEFAULT_STATISTICS_PREFS: StatisticsPrefs = {
  category: 'resources',
  days: 7,
  period: 'month',
  researchSelect: '9',
  lootTask: '',
  chartMode: 'line',
  chartAxisMode: 'separate',
  chartZeroBase: false,
  bucket: 0,
  rangeFrom: '',
  rangeTo: '',
  selectedKeys: {},
}

/** 逐项校验存储里的偏好：不合法或缺失的项一律回默认值。 */
export function readStatisticsPrefs(): StatisticsPrefs {
  try {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(PREFS_KEY) : null
    if (!raw) return { ...DEFAULT_STATISTICS_PREFS, selectedKeys: {} }
    const parsed: unknown = JSON.parse(raw)
    if (parsed && typeof parsed === 'object') {
      const obj = parsed as Record<string, unknown>
      const stored = <T,>(value: unknown, valid: readonly T[], fallback: T): T => valid.includes(value as T) ? value as T : fallback
      const d = DEFAULT_STATISTICS_PREFS

      const selectedKeys: Record<string, string[]> = {}
      if (obj.selectedKeys && typeof obj.selectedKeys === 'object') {
        for (const [key, value] of Object.entries(obj.selectedKeys as Record<string, unknown>)) {
          if (Array.isArray(value) && value.every(item => typeof item === 'string')) {
            selectedKeys[key] = [...new Set(value)]
          }
        }
      }

      return {
        category: stored(obj.category, VALID_CATEGORIES, d.category),
        days: stored(obj.days, VALID_DAYS, d.days),
        period: stored(obj.period, VALID_PERIODS, d.period),
        researchSelect: stored(obj.researchSelect, VALID_RESEARCH_SELECTS, d.researchSelect),
        lootTask: typeof obj.lootTask === 'string' && (obj.lootTask === '' || LOOT_TASK_PATTERN.test(obj.lootTask)) ? obj.lootTask : d.lootTask,
        chartMode: stored(obj.chartMode, VALID_CHART_MODES, d.chartMode),
        chartAxisMode: stored(obj.chartAxisMode, VALID_AXIS_MODES, d.chartAxisMode),
        chartZeroBase: typeof obj.chartZeroBase === 'boolean' ? obj.chartZeroBase : d.chartZeroBase,
        bucket: stored(obj.bucket, VALID_BUCKETS, d.bucket),
        rangeFrom: typeof obj.rangeFrom === 'string' ? obj.rangeFrom : '',
        rangeTo: typeof obj.rangeTo === 'string' ? obj.rangeTo : '',
        selectedKeys,
      }
    }
  } catch {
    /* 损坏偏好沿用默认配置。 */
  }
  return { ...DEFAULT_STATISTICS_PREFS, selectedKeys: {} }
}

let snapshot: StatisticsPrefs = readStatisticsPrefs()

/* 偏好是模块级快照：写入即通知订阅者，供同页的其它卡片跟着重算。 */
let version = 0
const listeners = new Set<() => void>()

/** 订阅偏好写入，返回退订函数。 */
export function subscribeStatisticsPrefs(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** 每次写入自增的版本号，供 useSyncExternalStore 感知快照变化。 */
export function getStatisticsPrefsVersion(): number {
  return version
}

/** 读取当前偏好快照；模块级单例，写入即整体替换引用。 */
export function getStatisticsPrefs(): StatisticsPrefs {
  return snapshot
}

/** 合并写入偏好并持久化：其余字段保持不变，selectedKeys 按类目合并而不是整体替换。 */
export function updateStatisticsPrefs(partial: Partial<StatisticsPrefs>) {
  snapshot = {
    ...snapshot,
    ...partial,
    selectedKeys: partial.selectedKeys ? { ...snapshot.selectedKeys, ...partial.selectedKeys } : snapshot.selectedKeys,
  }
  try {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(PREFS_KEY, JSON.stringify(snapshot))
    }
  } catch {
    /* 存储不可用时本次会话内仍生效。 */
  }

  version += 1
  for (const listener of listeners) listener()
}

/** 覆写单个类目的选中指标并去重。 */
export function setSelectedKeysForCategory(category: string, keys: string[]) {
  const nextKeys = {
    ...snapshot.selectedKeys,
    [category]: [...new Set(keys)],
  }
  updateStatisticsPrefs({ selectedKeys: nextKeys })
}

/** 返回该类目下仍可用的已选指标；存过的键全部失效时返回空数组。 */
export function getSelectedKeysForCategory(category: string, availableSeries: { key: string }[]): string[] {
  const saved = snapshot.selectedKeys[category]
  if (Array.isArray(saved) && saved.length > 0) {
    const valid = saved.filter(k => availableSeries.some(s => s.key === k))
    if (valid.length > 0) return valid
  }
  return []
}

/** 仅用于单元测试重置 snapshot 状态。 */
export function resetStatisticsPrefsForTest() {
  snapshot = readStatisticsPrefs()
}
