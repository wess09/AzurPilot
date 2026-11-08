/**
 * @fileoverview 预设与自定义配色方案计算、对比度判定与 CSS 变量生成。
 */
export const palettes = ['ocean', 'forest', 'violet', 'sand', 'slate'] as const
export type PresetPalette = typeof palettes[number]
export type Palette = PresetPalette | `custom:${string}`
/** 实际生效的明暗。自带色值的档位各自固定一个，其余由主题与系统决定。 */
export type ResolvedMode = 'light' | 'dark'
export type BrandColors = {primary: string; secondary: string}
export type CustomPalette = {id: `custom:${string}`; primary: string; secondary: string}

export const presetColors: Record<PresetPalette, Record<ResolvedMode, BrandColors>> = {
  ocean: {light: {primary: '#245dbe', secondary: '#147d83'}, dark: {primary: '#8ab4ff', secondary: '#71cbc9'}},
  forest: {light: {primary: '#286747', secondary: '#956020'}, dark: {primary: '#86cba3', secondary: '#dfb472'}},
  violet: {light: {primary: '#7050a3', secondary: '#a14865'}, dark: {primary: '#c1a4ee', secondary: '#efa2bb'}},
  sand: {light: {primary: '#915a2b', secondary: '#426b70'}, dark: {primary: '#e1b082', secondary: '#92c3c8'}},
  slate: {light: {primary: '#45566b', secondary: '#96553b'}, dark: {primary: '#acbdd2', secondary: '#dfaa8e'}},
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

export function paletteColors(palette: Palette, custom: CustomPalette[], mode: ResolvedMode): BrandColors {
  const match = custom.find(item => item.id === palette)
  if (match) return {primary: match.primary, secondary: match.secondary}
  return presetColors[palette as PresetPalette]?.[mode] ?? presetColors.ocean[mode]
}

function channels(color: string) {
  return [1, 3, 5].map(index => parseInt(color.slice(index, index + 2), 16))
}

export function mixColor(color: string, background: string, weight: number): string {
  const base = channels(background)
  return '#' + channels(color).map((value, index) => Math.round(value * weight + base[index] * (1 - weight)).toString(16).padStart(2, '0')).join('')
}

function luminance(color: string) {
  const rgb = channels(color).map(value => {
    const channel = value / 255
    return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4
  })
  return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722
}

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

/** 只写强调色这一族：强调色、悬停、按压、浅底与前景字色。 */
function accentTokensOn(colors: BrandColors, surface: string, mutedSurface: string, mode: ResolvedMode): Record<string, string> {
  const dark = mode === 'dark'
  const primary = readableColor(colors.primary, mutedSurface, mode)
  const secondary = readableColor(colors.secondary, mutedSurface, mode)
  return {
    '--accent': primary,
    '--accent-hover': mixColor(primary, dark ? '#ffffff' : '#000000', .85),
    '--accent-pressed': dark ? mixColor(primary, '#000000', .82) : mixColor(primary, '#000000', .70),
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
