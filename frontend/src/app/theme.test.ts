import { afterEach, describe, expect, it, vi } from 'vitest'
import { defaultMaterial, hasMaterialAxis, readThemePreference, showsRightRail, showsWallpaper, supportsBackground, usesGlassLayer, usesLegacyLayout, usesLegacyShell, usesMaterial, type Material, type Theme } from './theme'

afterEach(() => vi.unstubAllGlobals())

const NON_COMPACT_THEMES: Theme[] = ['light', 'dark', 'minimal', 'legacy-light', 'legacy-dark']

describe('主题偏好恢复', () => {
  it('将原深色主题迁移到现代深色', () => {
    vi.stubGlobal('localStorage', {getItem: (key: string) => key === 'azurpilot.theme' ? 'dark' : null})
    expect(readThemePreference()).toMatchObject({theme: 'legacy-dark', palette: 'ocean'})
  })
  it('简约与未知主题迁移到现代浅色', () => {
    vi.stubGlobal('localStorage', {getItem: (key: string) => key === 'azurpilot.theme' ? 'minimal' : 'forest'})
    expect(readThemePreference()).toMatchObject({theme: 'legacy-light', palette: 'forest'})
    vi.stubGlobal('localStorage', {getItem: () => 'unknown'})
    expect(readThemePreference()).toMatchObject({theme: 'legacy-light', palette: 'ocean'})
  })
  it('浏览器禁止存储时仍能启动', () => {
    vi.stubGlobal('localStorage', {getItem: () => {throw new Error('存储不可用')}})
    expect(readThemePreference()).toMatchObject({theme: 'legacy-light', palette: 'ocean'})
  })
  it('恢复自动模式与完整自定义方案，失效的方案选择回退到预设', () => {
    const custom = {id: 'custom:one', primary: '#123456', secondary: '#654321'}
    const saved: Record<string, string> = {'azurpilot.theme': 'minimal', 'azurpilot.palette': 'custom:one', 'azurpilot.color-mode': 'dark', 'azurpilot.custom-palettes': JSON.stringify([custom])}
    vi.stubGlobal('localStorage', {getItem: (key: string) => saved[key] ?? null})
    expect(readThemePreference()).toEqual({theme: 'legacy-dark', palette: 'custom:one', colorMode: 'dark', customPalettes: [custom], compactRailSide: 'right', compactRailWidth: 244, material: 'plain'})
    saved['azurpilot.custom-palettes'] = '{损坏的数据'
    saved['azurpilot.color-mode'] = 'invalid'
    expect(readThemePreference()).toEqual({theme: 'legacy-light', palette: 'ocean', colorMode: 'auto', customPalettes: [], compactRailSide: 'right', compactRailWidth: 244, material: 'plain'})
  })
  it('紧凑与未知主题迁移到现代浅色', () => {
    vi.stubGlobal('localStorage', {getItem: (key: string) => key === 'azurpilot.theme' ? 'extreme' : null})
    expect(readThemePreference()).toMatchObject({theme: 'legacy-light'})
    vi.stubGlobal('localStorage', {getItem: (key: string) => key === 'azurpilot.theme' ? 'huge' : null})
    expect(readThemePreference()).toMatchObject({theme: 'legacy-light'})
  })
})

// 紧凑布局偏好只在紧凑主题下有定义：位置决定列序，宽度决定右栏宽度；未知值必须回退，
// 否则 localStorage 里一个手改的值就能把网格列宽写成非法长度。
describe('紧凑布局偏好', () => {
  it('没有存过偏好时用计划栏在右与 244px', () => {
    vi.stubGlobal('localStorage', {getItem: () => null})
    expect(readThemePreference()).toMatchObject({compactRailSide: 'right', compactRailWidth: 244})
  })
  it('恢复计划栏在左与更宽档位', () => {
    const saved: Record<string, string> = {'azurpilot.compact-rail-side': 'left', 'azurpilot.compact-rail-width': '360'}
    vi.stubGlobal('localStorage', {getItem: (key: string) => saved[key] ?? null})
    expect(readThemePreference()).toMatchObject({compactRailSide: 'left', compactRailWidth: 360})
  })
  it('拒绝未知方向与档位外的宽度', () => {
    const saved: Record<string, string> = {'azurpilot.compact-rail-side': 'middle', 'azurpilot.compact-rail-width': '999'}
    vi.stubGlobal('localStorage', {getItem: (key: string) => saved[key] ?? null})
    expect(readThemePreference()).toMatchObject({compactRailSide: 'right', compactRailWidth: 244})
  })
})

// 白名单与装饰层判定共同决定毛玻璃、壁纸、标题遮罩与图表取色，改动主题集合时这两处必须同步。
describe('旧版主题注册与装饰层判定', () => {
  it('现代主题的浅色和深色都能恢复', () => {
    for (const theme of ['legacy-light', 'legacy-dark'] as const) {
      vi.stubGlobal('localStorage', {getItem: (key: string) => key === 'azurpilot.theme' ? theme : null})
      expect(readThemePreference().theme).toBe(theme)
    }
    vi.unstubAllGlobals()
  })
  it('只有 Apple 玻璃系主题使用材质装饰', () => {
    const material = NON_COMPACT_THEMES.filter(usesMaterial)
    expect(material).toEqual(['light', 'dark'])
  })
})

// 实例使用旧版版式时收起右栏，避免调度器出现两处。
describe('旧版版式的生效范围', () => {
  it('只有两个旧版主题在实例视图里换外壳', () => {
    for (const theme of NON_COMPACT_THEMES) {
      expect(usesLegacyShell(theme, 'alas')).toBe(usesLegacyLayout(theme))
    }
    expect(usesLegacyLayout('light')).toBe(false)
    expect(usesLegacyLayout('minimal')).toBe(false)
  })
  it('无实例时不启用实例外壳', () => {
    for (const theme of NON_COMPACT_THEMES) expect(usesLegacyShell(theme, undefined)).toBe(false)
    expect(usesLegacyShell('legacy-light', '')).toBe(false)
  })
  it('旧版主题的实例视图收起右栏，调度器与任务计划改由页内左列承载', () => {
    for (const theme of ['legacy-light', 'legacy-dark'] as Theme[]) {
      expect(showsRightRail(theme, 'alas')).toBe(false)
      expect(usesLegacyShell(theme, 'alas')).toBe(true)
    }
  })
  it('新版主题在任何实例页都保留右栏', () => {
    for (const theme of ['light', 'dark', 'minimal'] as Theme[]) {
      expect(showsRightRail(theme, 'alas')).toBe(true)
      expect(usesLegacyShell(theme, 'alas')).toBe(false)
    }
  })
  it('无实例时不渲染右栏', () => {
    for (const theme of NON_COMPACT_THEMES) expect(showsRightRail(theme, undefined)).toBe(false)
  })
})

// 材质轴只对「有材质轴」的家族成立：新版默认玻璃、旧版默认普通，简洁与紧凑的风格即非透明。
describe('材质轴偏好', () => {
  it('新版默认玻璃、旧版默认普通，其余家族没有材质轴', () => {
    vi.stubGlobal('localStorage', {getItem: () => null})
    expect(defaultMaterial('light')).toBe('glass')
    expect(defaultMaterial('dark')).toBe('glass')
    expect(defaultMaterial('legacy-light')).toBe('plain')
    expect(defaultMaterial('legacy-dark')).toBe('plain')
    expect(hasMaterialAxis('light')).toBe(true)
    expect(hasMaterialAxis('legacy-dark')).toBe(true)
    expect(hasMaterialAxis('minimal')).toBe(false)
    expect(hasMaterialAxis('extreme')).toBe(false)
  })

  it('存过的材质被恢复，非法值回退到该家族的默认', () => {
    vi.stubGlobal('localStorage', {getItem: (key: string) => key === 'azurpilot.theme' ? 'legacy-dark' : key === 'azurpilot.material' ? 'glass' : null})
    expect(readThemePreference()).toMatchObject({theme: 'legacy-dark', material: 'glass'})
    vi.stubGlobal('localStorage', {getItem: (key: string) => key === 'azurpilot.theme' ? 'light' : key === 'azurpilot.material' ? 'sparkle' : null})
    expect(readThemePreference()).toMatchObject({theme: 'legacy-light', material: 'plain'})
    vi.stubGlobal('localStorage', {getItem: (key: string) => key === 'azurpilot.theme' ? 'legacy-light' : null})
    expect(readThemePreference()).toMatchObject({theme: 'legacy-light', material: 'plain'})
  })

  it('玻璃层只在有材质轴的家族且材质为玻璃时成立', () => {
    expect(usesGlassLayer('light', 'glass')).toBe(true)
    expect(usesGlassLayer('legacy-light', 'glass')).toBe(true)
    expect(usesGlassLayer('light', 'plain')).toBe(false)
    expect(usesGlassLayer('legacy-light', 'plain')).toBe(false)
    expect(usesGlassLayer('minimal', 'glass')).toBe(false)
    expect(usesGlassLayer('extreme', 'glass')).toBe(false)
  })

  it('背景自定义对两个有材质轴的家族都开放，对简洁与紧凑不开放', () => {
    const withAxis: Theme[] = ['light', 'dark', 'legacy-light', 'legacy-dark']
    const without: Theme[] = ['minimal', 'extreme']
    for (const theme of withAxis) expect(supportsBackground(theme)).toBe(true)
    for (const theme of without) expect(supportsBackground(theme)).toBe(false)
  })

  it('材质与玻璃层的组合穷尽两个家族', () => {
    const materials: Material[] = ['glass', 'plain']
    const themes: Theme[] = ['light', 'dark', 'legacy-light', 'legacy-dark']
    for (const theme of themes) for (const material of materials) {
      expect(hasMaterialAxis(theme)).toBe(true)
      expect(usesGlassLayer(theme, material)).toBe(material === 'glass')
    }
  })
})

// 背景门控：有「关闭」档的材质由记录决定铺不铺，朴素家族任何时候都不铺。
describe('背景门控', () => {
  it('关了背景就不铺', () => {
    for (const theme of ['light', 'dark', 'legacy-light', 'legacy-dark'] as const) {
      expect(showsWallpaper(theme, 'off'), theme).toBe(false)
    }
  })

  it('随机图、网址与上传三档都铺', () => {
    for (const source of ['default', 'url', 'upload'] as const) {
      expect(showsWallpaper('light', source), source).toBe(true)
      expect(showsWallpaper('legacy-dark', source), source).toBe(true)
    }
  })

  it('简洁与紧凑任何时候都不铺', () => {
    for (const theme of ['minimal', 'extreme'] as const) {
      for (const source of ['off', 'default', 'url', 'upload'] as const) expect(showsWallpaper(theme, source)).toBe(false)
    }
  })
})
