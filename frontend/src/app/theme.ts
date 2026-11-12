/**
 * @fileoverview 主题偏好的读取、持久化与应用：解析最终明暗，把自定义外观写入 documentElement。
 */
import { applyColorOverrides } from './colorPalette'
import { colorModes, fixedColorModes, paletteColors, palettes, paletteTokens, readCustomPalettes, type ColorMode, type CustomPalette, type Palette, type ResolvedMode } from './palettes'
import { applyFamilyCustom } from './themeCustom'

/** 主题档位。旧版本存储的 dark / extreme 值在读取时迁移为对应的 legacy 档。 */
export type Theme = 'legacy-light' | 'legacy-dark' | 'minimal'
export type Material = 'glass' | 'plain'
/** 家族标识全集；本构建的自定义外观资源只按 legacy（THEME_FAMILY）提供。 */
export type Family = 'legacy' | 'new' | 'minimal' | 'extreme'
/** 本构建启用的主题家族：自定义外观（材质检视器等）按它读取对应资源。 */
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

/** 从 localStorage 读取主题偏好；键缺失或存储不可用时整体回落默认值，不抛错。 */
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

/**
 * 清掉上一次写入的变量，再应用当前主题的自定义外观。
 * 调色板永远最后写：它是最直接的「这一处就要这个色」，要压过品牌配色与整套配色。
 */
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

/** 当前生效的主题偏好，已附带解析后的明暗模式（resolvedMode）。 */
export const getThemePreference = () => preference
/** 订阅主题变更通知，返回退订函数。 */
export const subscribeTheme = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

function syncTheme(next: Preference) {
  const root = document.documentElement
  preference = {...next, resolvedMode: resolveMode(next)}
  root.classList.toggle('dark', preference.resolvedMode === 'dark')
  if (next.theme === 'minimal') root.dataset.colorMode = preference.resolvedMode
  else delete root.dataset.colorMode
  applyCustomLayer()
  listeners.forEach(listener => listener())
}

function systemModeChanged() {
  syncTheme(preference)
}

/**
 * 应用一份主题偏好：写 documentElement 的 data 标记并持久化到 localStorage（存储失败只影响持久化）。
 * 仅 minimal + auto 挂系统明暗监听；切到其他组合时卸掉监听。
 */
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
