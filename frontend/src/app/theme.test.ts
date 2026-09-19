import { afterEach, describe, expect, it, vi } from 'vitest'
import { readThemePreference } from './theme'

afterEach(() => vi.unstubAllGlobals())

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
  it('恢复紧凑主题，未知主题回退到浅色', () => {
    vi.stubGlobal('localStorage', {getItem: (key: string) => key === 'azurpilot.theme' ? 'extreme' : null})
    expect(readThemePreference()).toMatchObject({theme: 'extreme'})
    vi.stubGlobal('localStorage', {getItem: (key: string) => key === 'azurpilot.theme' ? 'huge' : null})
    expect(readThemePreference()).toMatchObject({theme: 'light'})
  })
})
