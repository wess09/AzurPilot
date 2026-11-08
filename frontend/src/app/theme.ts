/** 经典主题的明暗与材质偏好。 */
import { readCustomPalettes, type ResolvedMode, type CustomPalette } from './palettes'
import { applyFamilyCustom } from './themeCustom'

export type Theme = 'legacy-light' | 'legacy-dark'
export type Material = 'glass' | 'plain'
export type Family = 'legacy' | 'new' | 'minimal' | 'extreme'
export const THEME_FAMILY = 'legacy'

type Preference = {theme: Theme; material: Material; customPalettes: CustomPalette[]}
const defaults: Preference = {theme: 'legacy-light', material: 'plain', customPalettes: []}
const modeOfTheme = (theme: Theme): ResolvedMode => theme === 'legacy-dark' ? 'dark' : 'light'

/** 迁移旧皮肤，保留显式选择的明暗。程序员配色是旧固定模式里唯一的深色档。 */
function migrateTheme(theme: string | null, colorMode: string | null): Theme {
  if (theme === 'dark' || theme === 'legacy-dark') return 'legacy-dark'
  if ((theme === 'minimal' || theme === 'extreme') && (colorMode === 'dark' || colorMode === 'terminal')) return 'legacy-dark'
  return 'legacy-light'
}

export function readThemePreference(): Preference {
  try {
    const theme = migrateTheme(localStorage.getItem('azurpilot.theme'), localStorage.getItem('azurpilot.color-mode'))
    return {
      theme,
      material: localStorage.getItem('azurpilot.material') === 'glass' ? 'glass' : 'plain',
      customPalettes: readCustomPalettes(localStorage.getItem('azurpilot.custom-palettes')),
    }
  } catch { return {...defaults} }
}

const listeners = new Set<() => void>()
const initial = readThemePreference()
let preference = {...initial, resolvedMode: modeOfTheme(initial.theme)}
let customTokens: string[] = []

/** 清掉上一次写入的旋钮和品牌色，再应用当前覆盖项。 */
export function applyCustomLayer() {
  const root = document.documentElement
  for (const token of customTokens) root.style.removeProperty(token)
  customTokens = applyFamilyCustom(root, THEME_FAMILY, preference.resolvedMode)
}

export const getThemePreference = () => preference
export const subscribeTheme = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

export function applyTheme(next: Preference) {
  const root = document.documentElement
  root.dataset.theme = next.theme
  root.dataset.material = next.material
  preference = {...next, resolvedMode: modeOfTheme(next.theme)}
  applyCustomLayer()
  try {
    localStorage.setItem('azurpilot.theme', next.theme)
    localStorage.setItem('azurpilot.material', next.material)
  } catch { /* 存储不可用时仍允许切换，本次会话内生效。 */ }
  listeners.forEach(listener => listener())
}
