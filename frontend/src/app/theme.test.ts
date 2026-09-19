import { afterEach, describe, expect, it, vi } from 'vitest'
import { readThemePreference, showsRightRail, usesLegacyLayout, usesLegacyShell, usesMaterial, type Theme } from './theme'

afterEach(() => vi.unstubAllGlobals())

const ALL_THEMES: Theme[] = ['light', 'dark', 'minimal', 'legacy-light', 'legacy-dark']

describe('主题偏好恢复', () => {
  it('保留旧版浅深色偏好，并为缺少的配色提供默认值', () => {
    vi.stubGlobal('localStorage', {getItem: (key: string) => key === 'azurpilot.theme' ? 'dark' : null})
    expect(readThemePreference()).toMatchObject({theme: 'dark', palette: 'ocean'})
  })
  it('恢复简约配色并拒绝未知值', () => {
    vi.stubGlobal('localStorage', {getItem: (key: string) => key === 'azurpilot.theme' ? 'minimal' : 'forest'})
    expect(readThemePreference()).toMatchObject({theme: 'minimal', palette: 'forest'})
    vi.stubGlobal('localStorage', {getItem: () => 'unknown'})
    expect(readThemePreference()).toMatchObject({theme: 'light', palette: 'ocean'})
  })
  it('浏览器禁止存储时仍能启动', () => {
    vi.stubGlobal('localStorage', {getItem: () => {throw new Error('存储不可用')}})
    expect(readThemePreference()).toMatchObject({theme: 'light', palette: 'ocean'})
  })
  it('恢复自动模式与完整自定义方案，失效的方案选择回退到预设', () => {
    const custom = {id: 'custom:one', primary: '#123456', secondary: '#654321'}
    const saved: Record<string, string> = {'azurpilot.theme': 'minimal', 'azurpilot.palette': 'custom:one', 'azurpilot.color-mode': 'dark', 'azurpilot.custom-palettes': JSON.stringify([custom])}
    vi.stubGlobal('localStorage', {getItem: (key: string) => saved[key] ?? null})
    expect(readThemePreference()).toEqual({theme: 'minimal', palette: 'custom:one', colorMode: 'dark', customPalettes: [custom]})
    saved['azurpilot.custom-palettes'] = '{损坏的数据'
    saved['azurpilot.color-mode'] = 'invalid'
    expect(readThemePreference()).toEqual({theme: 'minimal', palette: 'ocean', colorMode: 'auto', customPalettes: []})
  })
})

// 白名单与装饰层判定共同决定毛玻璃、壁纸、标题遮罩与图表取色，改动主题集合时这两处必须同步。
describe('旧版主题注册与装饰层判定', () => {
  it('五个主题都能从存储里恢复', () => {
    for (const theme of ALL_THEMES) {
      vi.stubGlobal('localStorage', {getItem: (key: string) => key === 'azurpilot.theme' ? theme : null})
      expect(readThemePreference().theme).toBe(theme)
    }
    vi.unstubAllGlobals()
  })
  it('只有 Apple 玻璃系主题使用材质装饰', () => {
    const material = ALL_THEMES.filter(usesMaterial)
    expect(material).toEqual(['light', 'dark'])
  })
})

// 旧版版式只在实例视图生效：主页要留新版外壳，总览页要收起右栏免得调度器出现两处。
describe('旧版版式的生效范围', () => {
  it('只有两个旧版主题在实例视图里换外壳', () => {
    for (const theme of ALL_THEMES) {
      expect(usesLegacyShell(theme, 'alas')).toBe(usesLegacyLayout(theme))
    }
    expect(usesLegacyLayout('light')).toBe(false)
    expect(usesLegacyLayout('minimal')).toBe(false)
  })
  it('主页视图不换外壳', () => {
    for (const theme of ALL_THEMES) expect(usesLegacyShell(theme, undefined)).toBe(false)
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
  it('主页没有实例时不渲染右栏', () => {
    for (const theme of ALL_THEMES) expect(showsRightRail(theme, undefined)).toBe(false)
  })
})
