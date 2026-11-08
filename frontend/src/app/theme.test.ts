import { afterEach, describe, expect, it, vi } from 'vitest'
import { readThemePreference } from './theme'

afterEach(() => vi.unstubAllGlobals())

function storage(saved: Record<string, string>) {
  vi.stubGlobal('localStorage', {getItem: (key: string) => saved[key] ?? null})
}

describe('主题偏好恢复', () => {
  it.each([
    ['dark', 'auto', 'legacy-dark'],
    ['legacy-dark', 'auto', 'legacy-dark'],
    ['minimal', 'dark', 'legacy-dark'],
    ['extreme', 'terminal', 'legacy-dark'],
    ['extreme', 'retro-blue', 'legacy-light'],
    ['minimal', 'auto', 'legacy-light'],
    ['light', 'dark', 'legacy-light'],
    ['unknown', 'dark', 'legacy-light'],
  ])('把 %s / %s 恢复为 %s', (theme, colorMode, expected) => {
    storage({'azurpilot.theme': theme, 'azurpilot.color-mode': colorMode})
    expect(readThemePreference().theme).toBe(expected)
  })

  it('恢复已保存的材质与品牌配色', () => {
    const custom = {id: 'custom:one', primary: '#123456', secondary: '#654321'}
    storage({'azurpilot.material': 'glass', 'azurpilot.custom-palettes': JSON.stringify([custom])})
    expect(readThemePreference()).toEqual({theme: 'legacy-light', material: 'glass', customPalettes: [custom]})
  })

  it('偏好非法或存储不可用时使用默认值', () => {
    storage({'azurpilot.material': 'invalid', 'azurpilot.custom-palettes': '{损坏的数据'})
    const expected = {theme: 'legacy-light', material: 'plain', customPalettes: []}
    expect(readThemePreference()).toEqual(expected)
    vi.stubGlobal('localStorage', {getItem: () => {throw new Error('存储不可用')}})
    expect(readThemePreference()).toEqual(expected)
  })
})
