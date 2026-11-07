import { describe, expect, it } from 'vitest'
import { accentTokens, contrastRatio, fixedColorModes, paletteColors, paletteTokens, palettes, presetColors, readCustomPalettes, stockBrands, type CustomPalette } from './palettes'

const custom: CustomPalette = {id: 'custom:test', primary: '#ffffff', secondary: '#ffff00'}

describe('简约配色生成与校验', () => {
  it('预设在明暗模式下具有不同配色且保留可读性', () => {
    for (const id of palettes) {
      expect(presetColors[id].light).not.toEqual(presetColors[id].dark)
      for (const mode of ['light', 'dark'] as const) {
        const tokens = paletteTokens(presetColors[id][mode], mode)
        for (const background of ['--surface', '--surface-muted', '--accent-soft']) {
          expect(contrastRatio(tokens['--accent'], tokens[background])).toBeGreaterThanOrEqual(4.5)
        }
        expect(contrastRatio(tokens['--theme-on-accent'], tokens['--accent'])).toBeGreaterThanOrEqual(4.5)
      }
    }
  })
  it('自带色值的模式：对比度达标，程序员那一档保持纯灰阶', () => {
    for (const [id, fixed] of Object.entries(fixedColorModes)) {
      const tokens = fixed!.tokens
      expect(Object.values(tokens).every(value => /^#[\da-f]{6}$/i.test(value)), id).toBe(true)
      for (const background of ['--surface', '--surface-muted', '--accent-soft']) {
        expect(contrastRatio(tokens['--accent'], tokens[background]), `${id} 的 accent 落在 ${background} 上`).toBeGreaterThanOrEqual(4.5)
      }
      expect(contrastRatio(tokens['--theme-on-accent'], tokens['--accent']), `${id} 的按钮文字`).toBeGreaterThanOrEqual(4.5)
      expect(contrastRatio(tokens['--text'], tokens['--surface']), `${id} 的正文`).toBeGreaterThanOrEqual(7)
    }
    const isGray = (value: string) => value.slice(1, 3) === value.slice(3, 5) && value.slice(3, 5) === value.slice(5, 7)
    for (const value of Object.values(fixedColorModes.terminal!.tokens)) expect(isGray(value), value).toBe(true)
  })
  it('极端自定义颜色也能生成清晰的实色界面，浅色深色通用', () => {
    for (const mode of ['light', 'dark'] as const) {
      expect(paletteColors(custom.id, [custom], mode)).toEqual({primary: '#ffffff', secondary: '#ffff00'})
      const tokens = paletteTokens(paletteColors(custom.id, [custom], mode), mode)
      expect(Object.values(tokens).every(value => /^#[\da-f]{6}$/i.test(value))).toBe(true)
      expect(contrastRatio(tokens['--accent'], tokens['--surface-muted'])).toBeGreaterThanOrEqual(4.5)
      expect(contrastRatio(tokens['--secondary'], tokens['--surface-muted'])).toBeGreaterThanOrEqual(4.5)
    }
  })
  it('损坏、重复和非实色的存储条目不进入可选方案，并兼容旧版双色模式数据', () => {
    expect(readCustomPalettes('broken')).toEqual([])
    expect(readCustomPalettes('{}')).toEqual([])
    const legacy = {id: 'custom:legacy', name: '旧版配色', light: {primary: '#112233', secondary: '#445566'}, dark: {primary: '#778899', secondary: '#aabbcc'}}
    expect(readCustomPalettes(JSON.stringify([
      null, custom, custom,
      {...custom, id: 'custom:invalid', primary: 'red; background: url(test)', secondary: '#000000'},
      legacy,
    ]))).toEqual([
      custom,
      {id: 'custom:legacy', primary: '#112233', secondary: '#445566'},
    ])
    expect(paletteColors('custom:deleted', [], 'dark')).toEqual(presetColors.ocean.dark)
  })
})

describe('品牌配色只动强调色', () => {
  const ACCENT_KEYS = ['--accent', '--accent-hover', '--accent-pressed', '--accent-soft', '--secondary', '--secondary-soft', '--theme-on-accent']

  it('材质与旧版用它换色：不碰表面/文字/边框，材质层与底图才不会被冲掉', () => {
    const tokens = accentTokens({primary: '#7050a3', secondary: '#a14865'}, 'light')
    expect(Object.keys(tokens).sort()).toEqual([...ACCENT_KEYS].sort())
    expect(tokens['--accent']).toBe('#7050a3')
  })

  it('整块换色的 paletteTokens 仍然包含中性色（简约/紧凑走它）', () => {
    const tokens = paletteTokens({primary: '#7050a3', secondary: '#a14865'}, 'dark')
    for (const key of ['--surface', '--surface-muted', '--text', '--muted', '--border']) expect(tokens[key], key).toBeTruthy()
    for (const key of ACCENT_KEYS) expect(tokens[key], key).toBeTruthy()
  })

  it('四个大类都有原版色（色板第一项要用，缺了用户找不回原色）', () => {
    for (const family of ['new', 'legacy', 'minimal', 'extreme'] as const) {
      for (const mode of ['light', 'dark'] as const) {
        expect(stockBrands[family][mode].primary, family + mode).toMatch(/^#[0-9a-f]{6}$/i)
        expect(stockBrands[family][mode].secondary, family + mode).toMatch(/^#[0-9a-f]{6}$/i)
      }
    }
  })

  it('Windows 11 经典蓝在深浅色模式下均符合 WCAG 4.5:1 对比度标准', () => {
    const light = stockBrands.legacy.light
    const dark = stockBrands.legacy.dark
    expect(light.primary).toBe('#005fb8')
    expect(dark.primary).toBe('#60cdff')
    const lightTokens = accentTokens(light, 'light')
    const darkTokens = accentTokens(dark, 'dark')
    expect(contrastRatio(lightTokens['--accent'], '#ffffff')).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio(lightTokens['--theme-on-accent'], lightTokens['--accent'])).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio(darkTokens['--accent'], '#20252d')).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio(darkTokens['--theme-on-accent'], darkTokens['--accent'])).toBeGreaterThanOrEqual(4.5)
  })
})
