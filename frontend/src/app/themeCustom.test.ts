/**
 * @fileoverview 主题大类自定义的行为回归测试：存取、旧档迁移与 CSS 变量应用。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { applyFamilyCustom, clearFamilyKnob, clearFamilyPalette, clearFamilyRegion, readFamilyCustom, resetFamilyCustom, writeFamilyCustom } from './themeCustom'

// 注入独立的 localStorage 假实现：存取只发生在用例自己的字典里，不落真实存储。
const storage = (initial: Record<string, string> = {}) => {
  const data = {...initial}
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => data[key] ?? null,
    setItem: (key: string, value: string) => { data[key] = value },
    removeItem: (key: string) => { delete data[key] },
  })
  return data
}

// 假的根节点：只模拟 style 的 CSS 变量读写，applyFamilyCustom 写过哪些 token 可以直接断言。
const fakeRoot = () => {
  const values = new Map<string, string>()
  return {
    style: {
      setProperty: (key: string, value: string) => { values.set(key, value) },
      getPropertyValue: (key: string) => values.get(key) ?? '',
      removeProperty: (key: string) => { values.delete(key) },
    },
    values,
  }
}

afterEach(() => vi.unstubAllGlobals())

describe('按大类的区域参数', () => {
  it('没有存过时是空集（默认态零变化的来源）', () => {
    storage()
    expect(readFamilyCustom('new')).toEqual({params: {}})
    expect(readFamilyCustom('legacy')).toEqual({params: {}})
  })

  it('两个大类各存一套，互不串味', () => {
    storage()
    writeFamilyCustom('new', {params: {'plate.alpha': 60}})
    writeFamilyCustom('legacy', {params: {'plate.alpha': 90, 'surface.blur': 8}})
    expect(readFamilyCustom('new').params).toEqual({'plate.alpha': 60})
    expect(readFamilyCustom('legacy').params).toEqual({'plate.alpha': 90, 'surface.blur': 8})
  })

  it('损坏的数据当作没存过', () => {
    storage({'azurpilot.custom.new': '{不是 JSON'})
    expect(readFamilyCustom('new')).toEqual({params: {}})
  })

  it('溶解掉的语义区按层搬迁，目标层没有该旋钮就丢弃', () => {
    storage({'azurpilot.custom.legacy': JSON.stringify({params: {
      'sidebar.blur': 8, 'topbar.alpha': 70, 'segment.blur': 20, 'tab.radius': 12, 'chrome.alpha': 55,
    }})})
    expect(readFamilyCustom('legacy').params).toEqual({'surface.blur': 8, 'surface.alpha': 55})
  })

  it('弹窗与菜单是独立区域，旧值不被搬到一级面', () => {
    storage({'azurpilot.custom.legacy': JSON.stringify({params: {'modal.blur': 30, 'menu.alpha': 60}})})
    expect(readFamilyCustom('legacy').params).toEqual({'modal.blur': 30, 'menu.alpha': 60})
  })

  it('未知旋钮与越界值按目录处理', () => {
    storage({'azurpilot.custom.new': JSON.stringify({params: {'plate.alpha': 999, 'unknown.alpha': 50, 'surface.blur': -3, 'menu.radius': '4'}})})
    expect(readFamilyCustom('new').params).toEqual({'plate.alpha': 100, 'surface.blur': 0})
  })

  it('早期全局旋钮的记录折算到一级面（目录里没有的参数一并丢弃）', () => {
    storage({'azurpilot.custom.legacy': JSON.stringify({blur: 30, opacity: 40, radius: 6, shadow: 20, palette: 'ocean'})})
    const custom = readFamilyCustom('legacy')
    expect(custom.params).toEqual({'surface.blur': 30, 'surface.alpha': 40})
    expect(custom.palette).toBe('ocean')
  })

  it('只写用户动过的 token，并按目录取值', () => {
    storage({'azurpilot.custom.new': JSON.stringify({params: {'plate.alpha': 60, 'plate.blur': 12}})})
    const root = fakeRoot()
    const written = applyFamilyCustom(root as unknown as HTMLElement, 'new', 'light')
    expect(written).toEqual(['--theme-plate-alpha', '--theme-plate-blur'])
    expect(root.values.get('--theme-plate-alpha')).toBe('60%')
    expect(root.values.get('--theme-plate-blur')).toBe('12px')
    // 没动过的区域一个 token 都不写。
    expect(written.some(token => token.startsWith('--theme-surface-'))).toBe(false)
  })

  it('品牌配色与区域参数互不影响，清掉配色后参数仍在', () => {
    storage()
    writeFamilyCustom('new', {params: {'surface.alpha': 70}, palette: 'violet'})
    clearFamilyPalette('new')
    const custom = readFamilyCustom('new')
    expect(custom.palette).toBeUndefined()
    expect(custom.params).toEqual({'surface.alpha': 70})
  })

  it('单个旋钮、单个区域、整个大类都能分别还原', () => {
    storage()
    writeFamilyCustom('new', {params: {'plate.alpha': 60, 'plate.blur': 4, 'surface.alpha': 70}})
    clearFamilyKnob('new', 'plate.blur')
    expect(readFamilyCustom('new').params).toEqual({'plate.alpha': 60, 'surface.alpha': 70})
    clearFamilyRegion('new', 'plate')
    expect(readFamilyCustom('new').params).toEqual({'surface.alpha': 70})
    resetFamilyCustom('new')
    expect(readFamilyCustom('new').params).toEqual({})
    expect(applyFamilyCustom(fakeRoot() as unknown as HTMLElement, 'new', 'light')).toEqual([])
  })

  it('全部还原后不留键（无记录与默认态等价）', () => {
    const data = storage()
    writeFamilyCustom('legacy', {params: {'control.alpha': 50}})
    expect(data['azurpilot.custom.legacy']).toBeDefined()
    clearFamilyKnob('legacy', 'control.alpha')
    expect(data['azurpilot.custom.legacy']).toBeUndefined()
  })

  it('简洁与紧凑没有区域旋钮，一个 token 都不写', () => {
    storage({'azurpilot.custom.new': JSON.stringify({params: {'plate.alpha': 60}})})
    expect(applyFamilyCustom(fakeRoot() as unknown as HTMLElement, 'minimal', 'light')).toEqual([])
    expect(applyFamilyCustom(fakeRoot() as unknown as HTMLElement, 'extreme', 'light')).toEqual([])
  })

  it('切换大类时上一套用户层被清掉（不残留）', () => {
    storage({'azurpilot.custom.new': JSON.stringify({params: {'plate.alpha': 60}}), 'azurpilot.custom.legacy': JSON.stringify({params: {'surface.blur': 4}})})
    const root = fakeRoot()
    for (const token of applyFamilyCustom(root as unknown as HTMLElement, 'new', 'light')) root.style.removeProperty(token)
    const second = applyFamilyCustom(root as unknown as HTMLElement, 'legacy', 'light')
    expect(second).toContain('--theme-surface-blur')
    expect(root.values.get('--theme-plate-alpha')).toBeUndefined()
  })
})
