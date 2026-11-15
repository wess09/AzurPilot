/**
 * @fileoverview 调色板覆盖的持久化行为：令牌白名单、色值归一化与损坏存储的回落。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  clearColorOverrides, colorSlots, countColorOverrides, isColorToken,
  readColorOverride, readColorOverrides, toHexColor, writeColorOverride,
} from './colorPalette'

// 本文件跑在 node 环境，没有 localStorage：用内存桩代替，配合 vi.stubGlobal 验证读写路径。
function memoryStorage(initial: Record<string, string> = {}) {
  const data = {...initial}
  return {
    data,
    getItem: (key: string) => data[key] ?? null,
    setItem: (key: string, value: string) => { data[key] = value },
    removeItem: (key: string) => { delete data[key] },
  }
}

afterEach(() => vi.unstubAllGlobals())

describe('调色板覆盖表', () => {
  it('每个槽位只登记一次，且都指向 CSS 变量', () => {
    const tokens = colorSlots.map(slot => slot.token)
    expect(new Set(tokens).size).toBe(tokens.length)
    for (const token of tokens) expect(token.startsWith('--')).toBe(true)
    expect(isColorToken('--bg')).toBe(true)
    expect(isColorToken('--not-a-token')).toBe(false)
  })

  it('只接受登记过的令牌与合法实色', () => {
    vi.stubGlobal('localStorage', memoryStorage({
      'azurpilot.color-palette': JSON.stringify({
        light: {'--bg': '#123456', '--evil': '#000000', '--text': 'red', '--border': '#ABC'},
        dark: {'--surface': '#0a0b0c'},
        other: {'--bg': '#ffffff'},
      }),
    }))
    const overrides = readColorOverrides()
    expect(overrides.light).toEqual({'--bg': '#123456'})
    expect(overrides.dark).toEqual({'--surface': '#0a0b0c'})
    expect(readColorOverride('light', '--text')).toBeUndefined()
  })

  it('损坏或不可用的存储退回空表', () => {
    vi.stubGlobal('localStorage', memoryStorage({'azurpilot.color-palette': '{损坏'}))
    expect(readColorOverrides()).toEqual({})
    vi.stubGlobal('localStorage', {getItem: () => {throw new Error('不可用')}})
    expect(readColorOverrides()).toEqual({})
  })

  it('写入与还原分模式记账', () => {
    const storage = memoryStorage()
    vi.stubGlobal('localStorage', storage)
    writeColorOverride('light', '--bg', '#111111')
    writeColorOverride('dark', '--bg', '#222222')
    expect(countColorOverrides('light')).toBe(1)
    expect(countColorOverrides('dark')).toBe(1)
    writeColorOverride('light', '--bg', null)
    expect(countColorOverrides('light')).toBe(0)
    expect(countColorOverrides('dark')).toBe(1)
    // 两套都空时不留键，和从未改过完全等价。
    clearColorOverrides('dark')
    expect(storage.data['azurpilot.color-palette']).toBeUndefined()
  })

  it('非法色值不落盘', () => {
    const storage = memoryStorage()
    vi.stubGlobal('localStorage', storage)
    writeColorOverride('light', '--bg', 'color-mix(in srgb, red, blue)')
    writeColorOverride('light', '--nope', '#ffffff')
    expect(readColorOverrides()).toEqual({})
    expect(storage.data['azurpilot.color-palette']).toBeUndefined()
  })
})

describe('颜色归一化', () => {
  it.each([
    ['#AABBCC', '#aabbcc'],
    ['#abc', '#aabbcc'],
    ['rgb(17, 34, 51)', '#112233'],
    ['rgba(255, 255, 255, 0.5)', '#ffffff'],
    ['color-mix(in srgb, red, blue)', undefined],
    ['', undefined],
  ])('%s → %s', (input, expected) => {
    expect(toHexColor(input)).toBe(expected)
  })
})
