/** 现代与简约主题的浏览器偏好。 */
import { applyColorOverrides } from './colorPalette'
import { colorModes, fixedColorModes, paletteColors, palettes, paletteTokens, readCustomPalettes, type ColorMode, type CustomPalette, type Palette, type ResolvedMode } from './palettes'
import { applyFamilyCustom } from './themeCustom'

export type Theme = 'legacy-light' | 'legacy-dark' | 'minimal'
export type Material = 'glass' | 'plain'
export type Family = 'legacy' | 'new' | 'minimal' | 'extreme'
export const THEME_FAMILY = 'legacy'

type Preference = {theme: Theme; material: Material; palette: Palette; colorMode: ColorMode; customPalettes: CustomPalette[]}
const defaults: Preference = {theme: 'legacy-light', material: 'plain', palette: 'ocean', colorMode: 'auto', customPalettes: []}

/** 迁移旧皮肤，保留显式选择的明暗。程序员配色是旧固定模式里唯一的深色档。 */
function migrateTheme(theme: string | null, colorMode: string | null): Theme {
  if (theme === 'minimal') return 'minimal'
  if (theme === 'dark' || theme === 'legacy-dark') return 'legacy-dark'
  if (theme === 'extreme' && (colorMode === 'dark' || colorMode === 'terminal')) return 'legacy-dark'
  return 'legacy-light'
}

export function readThemePreference(): Preference {
  try {
    const colorMode = localStorage.getItem('azurpilot.color-mode') as ColorMode
    const palette = localStorage.getItem('azurpilot.palette') as Palette
    const customPalettes = readCustomPalettes(localStorage.getItem('azurpilot.custom-palettes'))
    return {
      theme: migrateTheme(localStorage.getItem('azurpilot.theme'), colorMode),
      material: localStorage.getItem('azurpilot.material') === 'glass' ? 'glass' : 'plain',
      colorMode: colorModes.includes(colorMode) ? colorMode : defaults.colorMode,
      palette: palettes.some(id => id === palette) || customPalettes.some(item => item.id === palette) ? palette : defaults.palette,
      customPalettes,
    }
  } catch { return {...defaults} }
}

const listeners = new Set<() => void>()
let systemQuery: MediaQueryList | undefined
let themeTokens: string[] = []

function resolveMode({theme, colorMode}: Preference): ResolvedMode {
  if (theme !== 'minimal') return theme === 'legacy-dark' ? 'dark' : 'light'
  return fixedColorModes[colorMode]?.mode ?? (colorMode === 'dark' || (colorMode === 'auto' && systemQuery?.matches) ? 'dark' : 'light')
}

const initial = readThemePreference()
let preference = {...initial, resolvedMode: resolveMode(initial)}

/** 清掉上一次写入的变量，再应用当前主题的自定义外观。
    调色板永远最后写：它是最直接的「这一处就要这个色」，要压过品牌配色与整套配色。 */
export function applyCustomLayer() {
  const root = document.documentElement
  for (const token of themeTokens) root.style.removeProperty(token)
  const {theme, colorMode, palette, customPalettes, resolvedMode} = preference
  if (theme !== 'minimal') {
    themeTokens = applyFamilyCustom(root, THEME_FAMILY, resolvedMode)
  } else {
    const tokens = fixedColorModes[colorMode]?.tokens ?? paletteTokens(paletteColors(palette, customPalettes, resolvedMode), resolvedMode)
    for (const [key, value] of Object.entries(tokens)) root.style.setProperty(key, value)
    themeTokens = Object.keys(tokens)
  }
  themeTokens = [...themeTokens, ...applyColorOverrides(root, resolvedMode)]
}

export const getThemePreference = () => preference
export const subscribeTheme = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

function syncTheme(next: Preference) {
  const root = document.documentElement
  preference = {...next, resolvedMode: resolveMode(next)}
  if (next.theme === 'minimal') root.dataset.colorMode = preference.resolvedMode
  else delete root.dataset.colorMode
  applyCustomLayer()
  listeners.forEach(listener => listener())
}

function systemModeChanged() {
  syncTheme(preference)
}

export function applyTheme(next: Preference) {
  const root = document.documentElement
  const minimal = next.theme === 'minimal'
  if (minimal && next.colorMode === 'auto' && typeof window.matchMedia === 'function') {
    if (!systemQuery) {
      systemQuery = window.matchMedia('(prefers-color-scheme: dark)')
      systemQuery.addEventListener('change', systemModeChanged)
    }
  } else {
    systemQuery?.removeEventListener('change', systemModeChanged)
    systemQuery = undefined
  }
  root.dataset.theme = next.theme
  if (minimal) delete root.dataset.material
  else root.dataset.material = next.material
  try {
    localStorage.setItem('azurpilot.theme', next.theme)
    localStorage.setItem('azurpilot.material', next.material)
    localStorage.setItem('azurpilot.color-mode', next.colorMode)
    localStorage.setItem('azurpilot.palette', next.palette)
    localStorage.setItem('azurpilot.custom-palettes', JSON.stringify(next.customPalettes))
  } catch { /* 存储不可用时仍允许切换，本次会话内生效。 */ }
  syncTheme(next)
}
