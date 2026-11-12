import { afterEach, describe, expect, it, vi } from 'vitest'

// 本地存储是浏览器接口，这里用内存替身；模块读取它是在导入时，所以每个用例都重新导入。
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
  return import('./dashboardPrefs')
}

// 与 dashboardPrefs.ts 的 PREFS_DEFAULTS 逐项一致；dogIcon 出厂即开，其余默认关。
const DEFAULTS = {fitCards: false, fitText: false, dense: false, merged: false, totalFirst: false, dogIcon: true}

afterEach(() => vi.unstubAllGlobals())

describe('仪表盘偏好', () => {
  it('默认状态除 dogIcon 外全关', async () => {
    const {readDashboardPrefs} = await loadPrefs()

    expect(readDashboardPrefs()).toEqual(DEFAULTS)
  })

  it('改一项存一项，重新导入后仍是这个状态', async () => {
    const first = await loadPrefs()
    first.setDashboardPref('dense', true)
    const saved = localStorage.getItem('azurpilot.dashboard')

    vi.resetModules()
    const second = await import('./dashboardPrefs')

    expect(saved).toContain('"dense":true')
    expect(second.readDashboardPrefs()).toEqual({...DEFAULTS, dense: true})
    expect(second.readDashboardPrefs()).toBe(second.readDashboardPrefs())
  })

  it('非布尔值按默认处理', async () => {
    vi.resetModules()
    vi.stubGlobal('localStorage', memoryStorage())
    localStorage.setItem('azurpilot.dashboard', JSON.stringify({dense: 'yes', merged: 1, fitCards: true}))
    const {readDashboardPrefs} = await import('./dashboardPrefs')

    expect(readDashboardPrefs()).toEqual({...DEFAULTS, fitCards: true})
  })
})
