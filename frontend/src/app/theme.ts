/**
 * @fileoverview 应用主题模式、明暗切换、紧凑布局与旧版外壳判定。
 */

import { palettes, readCustomPalettes, colorModes, fixedColorModes, type Palette, type ColorMode, type ResolvedMode, type CustomPalette } from './palettes'
import { applyFamilyCustom } from './themeCustom'
export type Theme = 'light' | 'dark' | 'minimal' | 'extreme'
  | 'legacy-light' | 'legacy-dark'
export { palettes } from './palettes'
export type { Palette, ColorMode, CustomPalette } from './palettes'

/** 紧凑主题专属：调度与任务计划栏相对内容区的位置。 */
export type CompactRailSide = 'left' | 'right'
/** 紧凑主题专属的右栏宽度档位，244px 与 compact.css 的默认值一致。 */
export const COMPACT_RAIL_WIDTHS = [200, 244, 300, 360] as const
export type CompactRailWidth = (typeof COMPACT_RAIL_WIDTHS)[number]
export const COMPACT_RAIL_DEFAULT_SIDE: CompactRailSide = 'right'
export const COMPACT_RAIL_DEFAULT_WIDTH: CompactRailWidth = 244

type Preference = {
  theme: Theme; palette: Palette; colorMode: ColorMode; customPalettes: CustomPalette[]
  compactRailSide: CompactRailSide; compactRailWidth: CompactRailWidth
  material: Material
}
const defaults: Preference = {
  theme: 'legacy-light', palette: 'ocean', colorMode: 'auto', customPalettes: [],
  compactRailSide: COMPACT_RAIL_DEFAULT_SIDE, compactRailWidth: COMPACT_RAIL_DEFAULT_WIDTH,
  material: 'plain',
}

/** 走 Apple 玻璃/壁纸/装饰动画一档的主题；旧版浅色与深色是朴素风格，不在此列。 */
const MATERIAL_THEMES: readonly Theme[] = ['light', 'dark']
export const usesMaterial = (theme: Theme) => MATERIAL_THEMES.includes(theme)

/** 有材质轴（玻璃 / 普通）的家族：新版与旧版。简洁与紧凑的风格即「非透明」，没有材质轴。 */
const MATERIAL_AXIS_THEMES: readonly Theme[] = ['light', 'dark', 'legacy-light', 'legacy-dark']
export const hasMaterialAxis = (theme: Theme) => MATERIAL_AXIS_THEMES.includes(theme)

/** 是否支持自定义背景：两个有材质轴的家族都支持，普通材质同样可开。 */
export const supportsBackground = (theme: Theme) => hasMaterialAxis(theme)

/** 是否铺背景：有关闭档的材质由记录决定铺不铺，简洁与紧凑任何时候都不铺。 */
export const showsWallpaper = (theme: Theme, source: 'off' | 'default' | 'url' | 'upload') =>
  supportsBackground(theme) && source !== 'off'

export type Material = 'glass' | 'plain'
export const MATERIALS: readonly Material[] = ['glass', 'plain']

/** 各家族的默认材质：新版是玻璃（现状），旧版是普通（现状）——默认态因此与加材质轴之前一致。 */
export const defaultMaterial = (theme: Theme): Material => (theme === 'light' || theme === 'dark') ? 'glass' : 'plain'

/** 玻璃层：半透明磨砂与壁纸由材质决定，与家族无关。 */
export const usesGlassLayer = (theme: Theme, material: Material) => hasMaterialAxis(theme) && material === 'glass'

/** 一级主题大类。家族内切换材质或明暗不改变已存的其他自定义项。 */
export type Family = 'new' | 'legacy' | 'minimal' | 'extreme'
export const familyOf = (theme: Theme): Family =>
  theme === 'light' || theme === 'dark' ? 'new'
    : theme === 'legacy-light' || theme === 'legacy-dark' ? 'legacy'
      : theme === 'extreme' ? 'extreme' : 'minimal'

/** 走旧版版式的主题：实例视图的顶栏跨全宽、总览页两列、右栏让位。 */
const LEGACY_LAYOUT_THEMES: readonly Theme[] = ['legacy-light', 'legacy-dark']
export const usesLegacyLayout = (theme: Theme) => LEGACY_LAYOUT_THEMES.includes(theme)

/** 实例视图是否换用旧版外壳。 */
export const usesLegacyShell = (theme: Theme, instance?: string) => Boolean(instance) && usesLegacyLayout(theme)

/** 是否渲染右栏。旧版主题把调度器与任务计划放进实例页左列，右栏整体让位，否则同一块内容会出现两处。 */
export const showsRightRail = (theme: Theme, instance?: string) => Boolean(instance) && !usesLegacyLayout(theme)

/** 旧的主题偏好迁移到现代主题，保留已选的明暗。 */
function modernTheme(theme: string | null, colorMode: ColorMode): 'legacy-light' | 'legacy-dark' {
  if (theme === 'dark' || theme === 'legacy-dark') return 'legacy-dark'
  if ((theme === 'minimal' || theme === 'extreme') && (colorMode === 'dark' || fixedColorModes[colorMode]?.mode === 'dark')) return 'legacy-dark'
  return 'legacy-light'
}

export function readThemePreference(): Preference {
  try {
    const theme = localStorage.getItem('azurpilot.theme')
    const palette = localStorage.getItem('azurpilot.palette')
    const savedColorMode = localStorage.getItem('azurpilot.color-mode')
    const colorMode = colorModes.includes(savedColorMode as ColorMode) ? savedColorMode as ColorMode : 'auto'
    const customPalettes = readCustomPalettes(localStorage.getItem('azurpilot.custom-palettes'))
    const railSide = localStorage.getItem('azurpilot.compact-rail-side')
    const railWidth = Number(localStorage.getItem('azurpilot.compact-rail-width'))
    const storedMaterial = localStorage.getItem('azurpilot.material')
    const resolvedTheme = modernTheme(theme, colorMode)
    return {
      theme: resolvedTheme,
      material: MATERIALS.includes(storedMaterial as Material) ? storedMaterial as Material : defaultMaterial(resolvedTheme),
      palette: palettes.some(item => item === palette) || customPalettes.some(item => item.id === palette) ? palette as Palette : 'ocean',
      colorMode,
      customPalettes,
      compactRailSide: railSide === 'left' || railSide === 'right' ? railSide : COMPACT_RAIL_DEFAULT_SIDE,
      compactRailWidth: COMPACT_RAIL_WIDTHS.includes(railWidth as CompactRailWidth) ? railWidth as CompactRailWidth : COMPACT_RAIL_DEFAULT_WIDTH,
    }
  } catch { return {...defaults} }
}

const listeners = new Set<() => void>()
let preference = {...readThemePreference(), resolvedMode: 'light' as ResolvedMode}
let revision = 0
let skinLoaded = false
/* 用户层写入的 token 记账：换大类或重置时据此清理，避免跟着新主题生效。 */
let customTokens: string[] = []

/** 有材质轴的家族由主题 id 定明暗（浅色/深色各是一个主题值），配色方案的自动与固定档位不适用于它们。 */
const modeOfTheme = (theme: Theme): ResolvedMode => theme === 'dark' || theme === 'legacy-dark' ? 'dark' : 'light'

/** 用户改动自定义旋钮或品牌配色后立即下发：先清上一套再写当前大类的一套（主题与皮肤都不动）。 */
export function applyCustomLayer() {
  const root = document.documentElement
  for (const token of customTokens) root.style.removeProperty(token)
  customTokens = applyFamilyCustom(root, familyOf(preference.theme), modeOfTheme(preference.theme))
}
export const getThemePreference = () => preference
export const subscribeTheme = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

/** 明暗与材质共用现代主题样式，只有首次启动需要加载。 */
export async function applyTheme(next: Preference) {
  const request = ++revision
  if (!skinLoaded) {
    const {default: css} = await import('../styles/legacy.css?inline')
    if (request !== revision) return
    let style = document.querySelector<HTMLStyleElement>('style[data-azurpilot-skin]')
    if (!style) {
      style = document.createElement('style')
      document.head.appendChild(style)
    }
    style.dataset.azurpilotSkin = 'legacy'
    style.textContent = css
    skinLoaded = true
  }

  const theme = modernTheme(next.theme, next.colorMode)
  const root = document.documentElement
  root.dataset.theme = theme
  root.dataset.material = next.material
  delete root.dataset.palette
  delete root.dataset.colorMode
  delete root.dataset.compactRail
  root.style.removeProperty('--right-rail-width')
  document.querySelector('link[data-azurpilot-theme]')?.remove()

  preference = {...next, theme, resolvedMode: modeOfTheme(theme)}
  applyCustomLayer()
  try {
    localStorage.setItem('azurpilot.theme', theme)
    localStorage.setItem('azurpilot.material', next.material)
  } catch { /* 存储不可用时仍允许切换，本次会话内生效。 */ }
  listeners.forEach(listener => listener())
}
