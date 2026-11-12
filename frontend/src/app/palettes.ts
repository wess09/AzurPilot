/**
 * @fileoverview 预设与自定义配色方案计算、对比度判定与 CSS 变量生成。
 */
export const palettes = ['ocean', 'forest', 'violet', 'sand', 'slate'] as const
type PresetPalette = typeof palettes[number]
export type Palette = PresetPalette | `custom:${string}`
export const colorModes = ['auto', 'light', 'dark', 'terminal', 'retro-gray', 'retro-blue', 'retro-red'] as const
export type ColorMode = typeof colorModes[number]

export type ResolvedMode = 'light' | 'dark'
type BrandColors = {primary: string; secondary: string}
export type CustomPalette = {id: `custom:${string}`; primary: string; secondary: string}

export const presetColors: Record<PresetPalette, Record<ResolvedMode, BrandColors>> = {
  ocean: {light: {primary: '#245dbe', secondary: '#147d83'}, dark: {primary: '#8ab4ff', secondary: '#71cbc9'}},
  forest: {light: {primary: '#286747', secondary: '#956020'}, dark: {primary: '#86cba3', secondary: '#dfb472'}},
  violet: {light: {primary: '#7050a3', secondary: '#a14865'}, dark: {primary: '#c1a4ee', secondary: '#efa2bb'}},
  sand: {light: {primary: '#915a2b', secondary: '#426b70'}, dark: {primary: '#e1b082', secondary: '#92c3c8'}},
  slate: {light: {primary: '#45566b', secondary: '#96553b'}, dark: {primary: '#acbdd2', secondary: '#dfaa8e'}},
}

type FixedMode = {mode: ResolvedMode; tokens: Record<string, string>}

/** 固定主题模式自带整套色值和明暗，优先于所选配色方案。 */
export const fixedColorModes: Partial<Record<ColorMode, FixedMode>> = {
  /* 程序员：黑灰白六级，模拟终端。 */
  terminal: {
    mode: 'dark',
    tokens: {
      '--bg': '#0b0b0b',
      '--surface': '#141414',
      '--surface-muted': '#1d1d1d',
      '--border': '#2b2b2b',
      '--muted': '#8c8c8c',
      '--text': '#e8e8e8',
      '--accent': '#f2f2f2',
      '--accent-hover': '#ffffff',
      '--accent-soft': '#232323',
      '--secondary': '#a0a0a0',
      '--secondary-soft': '#1f1f1f',
      '--theme-on-accent': '#111111',
    },
  },
  /* 复古灰：九十年代中期桌面观感 —— 青绿底、银灰窗体、深蓝标题栏。 */
  'retro-gray': {
    mode: 'light',
    tokens: {
      '--bg': '#008080',
      '--surface': '#c0c0c0',
      '--surface-muted': '#d4d0c8',
      '--border': '#808080',
      '--muted': '#404040',
      '--text': '#000000',
      '--accent': '#000080',
      '--accent-hover': '#0000a8',
      '--accent-soft': '#a8b0d0',
      '--secondary': '#006666',
      '--secondary-soft': '#a8c8c8',
      '--theme-on-accent': '#ffffff',
    },
  },
  /* 复古蓝：同期稍晚的一代 —— 蓝底、更亮的银灰、标题栏渐变色的深端。 */
  'retro-blue': {
    mode: 'light',
    tokens: {
      '--bg': '#3a6ea5',
      '--surface': '#d4d0c8',
      '--surface-muted': '#e4e0d8',
      '--border': '#858585',
      '--muted': '#4a4a4a',
      '--text': '#000000',
      '--accent': '#0a246a',
      '--accent-hover': '#143a94',
      '--accent-soft': '#b8c4dc',
      '--secondary': '#2f5d8a',
      '--secondary-soft': '#b4c8dc',
      '--theme-on-accent': '#ffffff',
    },
  },
  /* 复古红：米白机身加红色强调，八位机时代的塑料壳与按键色。 */
  'retro-red': {
    mode: 'light',
    tokens: {
      '--bg': '#e6e2da',
      '--surface': '#f7f5f0',
      '--surface-muted': '#dedad2',
      '--border': '#b5b0a6',
      '--muted': '#5c5850',
      '--text': '#1a1a1a',
      '--accent': '#a8121e',
      '--accent-hover': '#8c0e18',
      '--accent-soft': '#f2d5d7',
      '--secondary': '#1b4965',
      '--secondary-soft': '#d4e0e8',
      '--theme-on-accent': '#ffffff',
    },
  },
}

export const isHexColor = (value: unknown): value is string => typeof value === 'string' && /^#[\da-f]{6}$/i.test(value)
const validColors = (value: unknown): value is BrandColors => !!value && typeof value === 'object'
  && isHexColor((value as BrandColors).primary) && isHexColor((value as BrandColors).secondary)

/** 只接收完整的实色配置，避免损坏的本地数据进入 CSS。 */
export function readCustomPalettes(value: string | null): CustomPalette[] {
  try {
    const data: unknown = JSON.parse(value ?? '[]')
    if (!Array.isArray(data)) return []
    const result: CustomPalette[] = []
    for (const item of data.slice(0, 32)) {
      if (!item || typeof item.id !== 'string' || !/^custom:[\w-]{1,80}$/.test(item.id)
        || result.some(entry => entry.id === item.id)) continue
      let primary: string | undefined
      let secondary: string | undefined
      if (isHexColor((item as {primary?: unknown}).primary) && isHexColor((item as {secondary?: unknown}).secondary)) {
        primary = (item as {primary: string}).primary
        secondary = (item as {secondary: string}).secondary
      } else if (validColors((item as {light?: unknown}).light)) {
        primary = (item as {light: BrandColors}).light.primary
        secondary = (item as {light: BrandColors}).light.secondary
      }
      if (!primary || !secondary) continue
      result.push({id: item.id as `custom:${string}`, primary, secondary})
    }
    return result
  } catch { return [] }
}

/** 解析一个配色的品牌色：自定义配色按 id 优先，其次取预设的明暗版本，都没有则回落到 ocean。 */
export function paletteColors(palette: Palette, custom: CustomPalette[], mode: ResolvedMode): BrandColors {
  const match = custom.find(item => item.id === palette)
  if (match) return {primary: match.primary, secondary: match.secondary}
  return presetColors[palette as PresetPalette]?.[mode] ?? presetColors.ocean[mode]
}

function channels(color: string) {
  return [1, 3, 5].map(index => parseInt(color.slice(index, index + 2), 16))
}

function mixColor(color: string, background: string, weight: number): string {
  const base = channels(background)
  return '#' + channels(color).map((value, index) => Math.round(value * weight + base[index] * (1 - weight)).toString(16).padStart(2, '0')).join('')
}

/** WCAG 的 sRGB 相对亮度：先做 gamma 展开，再按 Rec.709 系数加权。 */
function luminance(color: string) {
  const rgb = channels(color).map(value => {
    const channel = value / 255
    return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4
  })
  return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722
}

/** 按 WCAG 公式计算两色的对比度；readableColor 以 4.5（AA 正文标准）为达标线。 */
export function contrastRatio(first: string, second: string): number {
  const a = luminance(first), b = luminance(second)
  return (Math.max(a, b) + .05) / (Math.min(a, b) + .05)
}

/** 保留所选色相，必要时调整明度，让链接和辅助文字在实色面板上清晰可读。 */
function readableColor(color: string, background: string, mode: ResolvedMode) {
  const target = mode === 'dark' ? '#ffffff' : '#000000'
  for (let step = 0; step <= 20; step++) {
    const adjusted = mixColor(target, color, step / 20)
    if (contrastRatio(adjusted, background) >= 4.5) return adjusted
  }
  return target
}

/** 品牌色一族从哪几个中性色算起；两份 token 共用这一套取值。 */
const brandBases = (mode: ResolvedMode) => ({
  dark: mode === 'dark',
  surface: mode === 'dark' ? '#20252d' : '#ffffff',
  mutedSurface: mode === 'dark' ? '#282f39' : '#edf2f7',
})

/** 只写强调色这一族：强调色、悬停、浅底与前景字色。 */
function accentTokensOn(colors: BrandColors, surface: string, mutedSurface: string, mode: ResolvedMode): Record<string, string> {
  const dark = mode === 'dark'
  const primary = readableColor(colors.primary, mutedSurface, mode)
  const secondary = readableColor(colors.secondary, mutedSurface, mode)
  return {
    '--accent': primary,
    '--accent-hover': mixColor(primary, dark ? '#ffffff' : '#000000', .85),
    '--accent-soft': mixColor(primary, surface, dark ? .12 : .07),
    '--secondary': secondary,
    '--secondary-soft': mixColor(secondary, surface, dark ? .12 : .07),
    '--theme-on-accent': contrastRatio(primary, '#ffffff') >= contrastRatio(primary, '#17202b') ? '#ffffff' : '#17202b',
  }
}

/** 色板第一项跟随经典主题的原版强调色。 */
export const stockBrands: Record<ResolvedMode, BrandColors> = {
  light: {primary: '#005fb8', secondary: '#0078d4'},
  dark: {primary: '#60cdff', secondary: '#4cc2ff'},
}

/** 只改强调色一族，不碰中性色（表面/文字/边框归主题自己管）——材质与旧版要的就是这一份。 */
export function accentTokens(colors: BrandColors, mode: ResolvedMode): Record<string, string> {
  const {surface, mutedSurface} = brandBases(mode)
  return accentTokensOn(colors, surface, mutedSurface, mode)
}

/** 整块换色：中性色也一起换，简约与紧凑走这一份。 */
export function paletteTokens(colors: BrandColors, mode: ResolvedMode): Record<string, string> {
  const {dark, surface, mutedSurface} = brandBases(mode)
  return {
    ...accentTokensOn(colors, surface, mutedSurface, mode),
    '--bg': mixColor(colors.primary, dark ? '#14181e' : '#f5f7fa', .025),
    '--surface': surface, '--surface-muted': mutedSurface,
    '--text': dark ? '#e5ebf3' : '#243447', '--muted': dark ? '#a5b2c3' : '#5b6d80',
    '--border': dark ? '#424d5d' : '#d5dee8',
  }
}
