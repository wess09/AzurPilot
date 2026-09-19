import { palettes, paletteColors, paletteTokens, readCustomPalettes, type Palette, type ColorMode, type ResolvedMode, type CustomPalette } from './palettes'
export type Theme = 'light' | 'dark' | 'minimal' | 'extreme'
export { palettes } from './palettes'
export type { Palette, ColorMode, CustomPalette } from './palettes'
type Preference = {theme: Theme; palette: Palette; colorMode: ColorMode; customPalettes: CustomPalette[]}
const defaults: Preference = {theme: 'light', palette: 'ocean', colorMode: 'auto', customPalettes: []}

export function readThemePreference(): Preference {
  try {
    const theme = localStorage.getItem('azurpilot.theme')
    const palette = localStorage.getItem('azurpilot.palette')
    const colorMode = localStorage.getItem('azurpilot.color-mode')
    const customPalettes = readCustomPalettes(localStorage.getItem('azurpilot.custom-palettes'))
    return {
      theme: theme === 'dark' || theme === 'minimal' || theme === 'extreme' ? theme : 'light',
      palette: palettes.some(item => item === palette) || customPalettes.some(item => item.id === palette) ? palette as Palette : 'ocean',
      colorMode: colorMode === 'light' || colorMode === 'dark' ? colorMode : 'auto',
      customPalettes,
    }
  } catch { return {...defaults} }
}

const listeners = new Set<() => void>()
let preference = {...readThemePreference(), resolvedMode: 'light' as ResolvedMode}
let revision = 0
let activeSkin: string | undefined
let systemQuery: MediaQueryList | undefined
let managedTokens: string[] = []
export const getThemePreference = () => preference
export const subscribeTheme = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

/** 只有简约与紧凑的自动模式订阅系统变化；切换为固定模式或经典主题即移除监听。 */
function applyColorMode(next: Preference) {
  const root = document.documentElement
  const minimal = next.theme === 'minimal' || next.theme === 'extreme'
  const followSystem = minimal && next.colorMode === 'auto'
  if (!followSystem) {
    systemQuery?.removeEventListener('change', systemModeChanged)
    systemQuery = undefined
  } else if (!systemQuery) {
    systemQuery = window.matchMedia('(prefers-color-scheme: dark)')
    systemQuery.addEventListener('change', systemModeChanged)
  }
  const resolvedMode = minimal ? (next.colorMode === 'auto' ? systemQuery?.matches ? 'dark' : 'light' : next.colorMode) : next.theme === 'dark' ? 'dark' : 'light'
  if (minimal) {
    const tokens = paletteTokens(paletteColors(next.palette, next.customPalettes, resolvedMode), resolvedMode)
    // 同一轮更新内联变量，让图表的属性监听合并处理本次变化。
    for (const key of managedTokens) if (!(key in tokens)) root.style.removeProperty(key)
    for (const [key, value] of Object.entries(tokens)) {
      if (root.style.getPropertyValue(key) !== value) root.style.setProperty(key, value)
    }
    managedTokens = Object.keys(tokens)
    if (root.dataset.colorMode !== resolvedMode) root.dataset.colorMode = resolvedMode
  } else {
    for (const key of managedTokens) root.style.removeProperty(key)
    managedTokens = []
    delete root.dataset.colorMode
  }
  return resolvedMode
}

function systemModeChanged() {
  preference = {...preference, resolvedMode: applyColorMode(preference)}
  listeners.forEach(listener => listener())
}

/** 样式作为惰性文本模块加载，切换时替换唯一节点，避免旧主题规则驻留。 */
export async function applyTheme(next: Preference) {
  const request = ++revision
  // 「紧凑」复用极简皮肤，紧凑规则由 compact.css 叠加；浅色/深色走经典皮肤。
  const skin = next.theme === 'minimal' || next.theme === 'extreme' ? 'minimal' : 'classic'
  let css: string | undefined
  if (activeSkin !== skin) {
    const module = skin === 'minimal'
      ? await import('../styles/minimal.css?inline')
      : await import('../styles/classic.css?inline')
    css = module.default
  }
  // 快速切换时只提交最后一次选择，较早返回的请求不能覆盖新主题。
  if (request !== revision) return
  if (css !== undefined) {
    let style = document.querySelector<HTMLStyleElement>('style[data-azurpilot-skin]')
    if (!style) {
      style = document.createElement('style')
      document.head.appendChild(style)
    }
    style.dataset.azurpilotSkin = skin
    style.textContent = css
    activeSkin = skin
  }
  const custom = document.querySelector('link[data-azurpilot-theme]')
  if (skin === 'minimal') custom?.remove()
  else if (!custom) {
    const link = document.createElement('link')
    link.rel = 'stylesheet'
    link.href = `${import.meta.env.BASE_URL}theme.css`
    link.dataset.azurpilotTheme = 'user'
    document.head.appendChild(link)
  }
  const root = document.documentElement
  if (root.dataset.theme !== next.theme) root.dataset.theme = next.theme
  if (root.dataset.palette !== next.palette) root.dataset.palette = next.palette
  const resolvedMode = applyColorMode(next)
  try {
    localStorage.setItem('azurpilot.theme', next.theme)
    localStorage.setItem('azurpilot.palette', next.palette)
    localStorage.setItem('azurpilot.color-mode', next.colorMode)
    localStorage.setItem('azurpilot.custom-palettes', JSON.stringify(next.customPalettes))
  } catch { /* 存储不可用时仍允许切换，本次会话内生效。 */ }
  preference = {...next, resolvedMode}
  listeners.forEach(listener => listener())
}
