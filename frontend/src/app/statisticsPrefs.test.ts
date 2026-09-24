import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  DEFAULT_STATISTICS_PREFS,
  PREFS_KEY,
} from './statisticsPrefs'

function memoryStorage() {
  const map = new Map<string, string>()
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => void map.set(key, value),
    removeItem: (key: string) => void map.delete(key),
  }
}

async function loadPrefs() {
  vi.resetModules()
  vi.stubGlobal('localStorage', memoryStorage())
  return import('./statisticsPrefs')
}

afterEach(() => vi.unstubAllGlobals())

describe('统计页与图表选项持久化', () => {
  it('未存储时返回规范默认值', async () => {
    const { readStatisticsPrefs, getStatisticsPrefs } = await loadPrefs()

    expect(readStatisticsPrefs()).toEqual({ ...DEFAULT_STATISTICS_PREFS, selectedKeys: {} })
    expect(getStatisticsPrefs()).toEqual({ ...DEFAULT_STATISTICS_PREFS, selectedKeys: {} })
  })

  it('更新偏好写入 localStorage 并在重新加载时完整还原', async () => {
    const first = await loadPrefs()
    first.updateStatisticsPrefs({
      category: 'opsi',
      days: 30,
      period: 'week',
      researchSelect: 'consumable',
      chartMode: 'candlestick',
      chartAxisMode: 'unified',
      bucket: 60,
    })

    const raw = localStorage.getItem(PREFS_KEY)
    expect(raw).toBeTruthy()
    expect(raw).toContain('"category":"opsi"')
    expect(raw).toContain('"days":30')
    expect(raw).toContain('"bucket":60')

    vi.resetModules()
    const second = await import('./statisticsPrefs')
    expect(second.readStatisticsPrefs()).toEqual({
      category: 'opsi',
      days: 30,
      period: 'week',
      researchSelect: 'consumable',
      chartMode: 'candlestick',
      chartAxisMode: 'unified',
      bucket: 60,
      selectedKeys: {},
    })
  })

  it('按分类独立记录指标选择，且能按可用系列安全校验与过滤', async () => {
    const prefs = await loadPrefs()

    // 记录 resources 与 opsi 分类的指标
    prefs.setSelectedKeysForCategory('resources', ['oil', 'cube', 'ghost_key'])
    prefs.setSelectedKeysForCategory('opsi', ['ap', 'yellow_coins'])

    const availableResources = [{ key: 'oil' }, { key: 'cube' }, { key: 'coin' }]
    const availableOpsi = [{ key: 'ap' }, { key: 'yellow_coins' }, { key: 'purple_coins' }]

    // 自动过滤掉当前系列不存在的 ghost_key
    expect(prefs.getSelectedKeysForCategory('resources', availableResources)).toEqual(['oil', 'cube'])
    expect(prefs.getSelectedKeysForCategory('opsi', availableOpsi)).toEqual(['ap', 'yellow_coins'])

    // 如果可用列表中没有匹配项，返回空数组以便回退默认
    expect(prefs.getSelectedKeysForCategory('resources', [{ key: 'coin' }])).toEqual([])
    expect(prefs.getSelectedKeysForCategory('commission', [{ key: 'exp' }])).toEqual([])
  })

  it('处理异常或损坏的存储值时安全回退，避免界面崩溃', async () => {
    vi.resetModules()
    vi.stubGlobal('localStorage', memoryStorage())
    localStorage.setItem(
      PREFS_KEY,
      JSON.stringify({
        category: 'invalid_category',
        days: 9999,
        period: 'year',
        researchSelect: 'nonsense',
        chartMode: 'pie',
        chartAxisMode: 'random',
        bucket: 12345,
        selectedKeys: 'not_an_object',
      }),
    )

    const { readStatisticsPrefs } = await import('./statisticsPrefs')
    const loaded = readStatisticsPrefs()

    expect(loaded.category).toBe(DEFAULT_STATISTICS_PREFS.category)
    expect(loaded.days).toBe(DEFAULT_STATISTICS_PREFS.days)
    expect(loaded.period).toBe(DEFAULT_STATISTICS_PREFS.period)
    expect(loaded.researchSelect).toBe(DEFAULT_STATISTICS_PREFS.researchSelect)
    expect(loaded.chartMode).toBe(DEFAULT_STATISTICS_PREFS.chartMode)
    expect(loaded.chartAxisMode).toBe(DEFAULT_STATISTICS_PREFS.chartAxisMode)
    expect(loaded.bucket).toBe(DEFAULT_STATISTICS_PREFS.bucket)
    expect(loaded.selectedKeys).toEqual({})
  })
})
