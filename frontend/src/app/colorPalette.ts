/**
 * @fileoverview 全量调色板：把界面契约里的每个颜色令牌登记为可编辑槽位，并按明暗分别存档。
 *
 * 槽位一律指向主题已经在消费的 CSS 变量，因此改一个值会同时改掉所有用到它的地方
 * （面板、卡片、弹窗、图表、日志……），不需要逐条样式覆盖。派生令牌（`var(--...)`
 * 或 `color-mix()` 合成出来的）不单独挂牌，改它的源头即可。
 */
import type { UiKey } from '../i18n'
import type { ResolvedMode } from './palettes'

type ColorGroup = 'surface' | 'text' | 'accent' | 'status' | 'nav' | 'form' | 'log' | 'syntax' | 'chart'

/** 全部分组标识，设置页调色板按此数组顺序分节展示。 */
export const colorGroups: ColorGroup[] = ['surface', 'text', 'accent', 'status', 'nav', 'form', 'log', 'syntax', 'chart']

/** 各分组在设置页的标题 i18n 键。 */
export const colorGroupLabels: Record<ColorGroup, UiKey> = {
  surface: 'settings.colorGroupSurface',
  text: 'settings.colorGroupText',
  accent: 'settings.colorGroupAccent',
  status: 'settings.colorGroupStatus',
  nav: 'settings.colorGroupNav',
  form: 'settings.colorGroupForm',
  log: 'settings.colorGroupLog',
  syntax: 'settings.colorGroupSyntax',
  chart: 'settings.colorGroupChart',
}

/** 一个可编辑颜色槽位：token 是主题已在消费的 CSS 变量名，label 是设置页的展示文案键。 */
export type ColorSlot = {token: `--${string}`; group: ColorGroup; label: UiKey}

/** 挂牌顺序即界面顺序：先面、再字、再强调，其余按使用频率排开。 */
export const colorSlots: ColorSlot[] = [
  {token: '--bg', group: 'surface', label: 'settings.colorSlotBg'},
  {token: '--surface', group: 'surface', label: 'settings.colorSlotSurface'},
  {token: '--surface-muted', group: 'surface', label: 'settings.colorSlotSurfaceMuted'},
  {token: '--border', group: 'surface', label: 'settings.colorSlotBorder'},

  {token: '--text', group: 'text', label: 'settings.colorSlotText'},
  {token: '--muted', group: 'text', label: 'settings.colorSlotMuted'},
  {token: '--theme-on-accent', group: 'text', label: 'settings.colorSlotOnAccent'},
  {token: '--theme-on-danger', group: 'text', label: 'settings.colorSlotOnDanger'},

  {token: '--accent', group: 'accent', label: 'settings.colorSlotAccent'},
  {token: '--accent-hover', group: 'accent', label: 'settings.colorSlotAccentHover'},
  {token: '--accent-soft', group: 'accent', label: 'settings.colorSlotAccentSoft'},
  {token: '--secondary', group: 'accent', label: 'settings.colorSlotSecondary'},
  {token: '--secondary-soft', group: 'accent', label: 'settings.colorSlotSecondarySoft'},

  {token: '--red', group: 'status', label: 'settings.colorSlotDanger'},
  {token: '--theme-danger-soft', group: 'status', label: 'settings.colorSlotDangerSoft'},
  {token: '--green', group: 'status', label: 'settings.colorSlotSuccess'},
  {token: '--green-soft', group: 'status', label: 'settings.colorSlotSuccessSoft'},
  {token: '--theme-warning', group: 'status', label: 'settings.colorSlotWarning'},
  {token: '--theme-warning-soft', group: 'status', label: 'settings.colorSlotWarningSoft'},

  {token: '--theme-nav-icon', group: 'nav', label: 'settings.colorSlotNavIcon'},
  {token: '--theme-nav-active-bg', group: 'nav', label: 'settings.colorSlotNavActiveBg'},
  {token: '--theme-nav-active-text', group: 'nav', label: 'settings.colorSlotNavActiveText'},
  {token: '--theme-nav-hover-bg', group: 'nav', label: 'settings.colorSlotNavHoverBg'},
  {token: '--theme-nav-expanded-bg', group: 'nav', label: 'settings.colorSlotNavExpandedBg'},

  {token: '--theme-input-border', group: 'form', label: 'settings.colorSlotInputBorder'},
  {token: '--theme-toggle-off', group: 'form', label: 'settings.colorSlotToggleOff'},
  {token: '--theme-toggle-on', group: 'form', label: 'settings.colorSlotToggleOn'},
  {token: '--theme-toggle-knob', group: 'form', label: 'settings.colorSlotToggleKnob'},
  {token: '--theme-scrollbar-thumb', group: 'form', label: 'settings.colorSlotScrollbar'},

  {token: '--theme-log-debug', group: 'log', label: 'settings.colorSlotLogDebug'},
  {token: '--theme-log-info', group: 'log', label: 'settings.colorSlotLogInfo'},
  {token: '--theme-log-warning', group: 'log', label: 'settings.colorSlotLogWarning'},
  {token: '--theme-log-error', group: 'log', label: 'settings.colorSlotLogError'},
  {token: '--theme-log-critical', group: 'log', label: 'settings.colorSlotLogCritical'},
  {token: '--theme-log-time', group: 'log', label: 'settings.colorSlotLogTime'},
  {token: '--theme-log-true', group: 'log', label: 'settings.colorSlotLogTrue'},
  {token: '--theme-log-false', group: 'log', label: 'settings.colorSlotLogFalse'},
  {token: '--theme-log-null', group: 'log', label: 'settings.colorSlotLogNull'},
  {token: '--theme-log-path', group: 'log', label: 'settings.colorSlotLogPath'},
  {token: '--theme-log-attr', group: 'log', label: 'settings.colorSlotLogAttr'},

  {token: '--syntax-key', group: 'syntax', label: 'settings.colorSlotSyntaxKey'},
  {token: '--syntax-string', group: 'syntax', label: 'settings.colorSlotSyntaxString'},
  {token: '--syntax-value', group: 'syntax', label: 'settings.colorSlotSyntaxValue'},
  {token: '--syntax-comment', group: 'syntax', label: 'settings.colorSlotSyntaxComment'},
  {token: '--syntax-punctuation', group: 'syntax', label: 'settings.colorSlotSyntaxPunctuation'},

  {token: '--theme-chart-primary', group: 'chart', label: 'settings.colorSlotChartPrimary'},
  {token: '--theme-chart-secondary', group: 'chart', label: 'settings.colorSlotChartSecondary'},
  {token: '--theme-chart-rise', group: 'chart', label: 'settings.colorSlotChartRise'},
  {token: '--theme-chart-fall', group: 'chart', label: 'settings.colorSlotChartFall'},
]

const slotTokens = new Set<string>(colorSlots.map(slot => slot.token))

/** 是否为登记过的槽位令牌：未登记的令牌不进覆盖表，也不会写进根节点。 */
export const isColorToken = (token: string) => slotTokens.has(token)

/** 只接受实色：`#rgb` 输入时补齐成六位，其余（rgb()/color-mix/named）一律判为无效。 */
export const colorHex = /^#[\da-f]{6}$/i

/** 计算样式可能给 `rgb(…)`，统一折成六位十六进制；认不出就返回 undefined。 */
export function toHexColor(raw: string): string | undefined {
  const value = raw.trim()
  if (colorHex.test(value)) return value.toLowerCase()
  const short = /^#([\da-f])([\da-f])([\da-f])$/i.exec(value)
  if (short) return `#${short[1]}${short[1]}${short[2]}${short[2]}${short[3]}${short[3]}`.toLowerCase()
  const rgb = /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/i.exec(value)
  if (!rgb) return undefined
  return '#' + rgb.slice(1, 4).map(channel => Math.max(0, Math.min(255, Math.round(Number(channel)))).toString(16).padStart(2, '0')).join('')
}

const STORAGE_KEY = 'azurpilot.color-palette'

/** 每个明暗各存一份覆盖；缺省即「跟随主题」。 */
type ColorOverrides = Partial<Record<ResolvedMode, Record<string, string>>>

/** 只接收登记过的令牌与合法实色，避免本地数据把任意 CSS 写进根节点。 */
export function readColorOverrides(): ColorOverrides {
  try {
    const data: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}')
    if (!data || typeof data !== 'object') return {}
    const result: ColorOverrides = {}
    for (const mode of ['light', 'dark'] as const) {
      const raw = (data as Record<string, unknown>)[mode]
      if (!raw || typeof raw !== 'object') continue
      const accepted = Object.entries(raw as Record<string, unknown>)
        .filter(([token, value]) => isColorToken(token) && typeof value === 'string' && colorHex.test(value))
        .map(([token, value]) => [token, (value as string).toLowerCase()])
      if (accepted.length) result[mode] = Object.fromEntries(accepted)
    }
    return result
  } catch { return {} }
}

function save(overrides: ColorOverrides) {
  try {
    if (Object.values(overrides).some(entries => entries && Object.keys(entries).length)) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(overrides))
    } else localStorage.removeItem(STORAGE_KEY)
  } catch { /* 存储不可用时仍允许本次会话内改色。 */ }
}

/** 读单个槽位在指定明暗下的覆盖值，未覆盖返回 undefined。 */
export function readColorOverride(mode: ResolvedMode, token: string): string | undefined {
  return readColorOverrides()[mode]?.[token]
}

/** 写入或清除单个槽位；value 传 null 表示还原。返回写入后的覆盖表。 */
export function writeColorOverride(mode: ResolvedMode, token: string, value: string | null): ColorOverrides {
  const overrides = readColorOverrides()
  if (!isColorToken(token)) return overrides
  const entries = {...overrides[mode]}
  if (value && colorHex.test(value)) entries[token] = value.toLowerCase()
  else delete entries[token]
  const next: ColorOverrides = {...overrides}
  if (Object.keys(entries).length) next[mode] = entries
  else delete next[mode]
  save(next)
  return next
}

/** 清空覆盖并返回清空后的覆盖表：不传 mode 清掉全部明暗，传了只清该明暗。 */
export function clearColorOverrides(mode?: ResolvedMode): ColorOverrides {
  const overrides = readColorOverrides()
  const next: ColorOverrides = {...overrides}
  if (mode) delete next[mode]
  else { delete next.light; delete next.dark }
  save(next)
  return next
}

/** 指定明暗下已覆盖的槽位数：直读存储，需要新鲜值时由调用方用版本号或弹窗开合强制重算。 */
export function countColorOverrides(mode: ResolvedMode): number {
  return Object.keys(readColorOverrides()[mode] ?? {}).length
}

/** 把该明暗的覆盖写进根节点，返回写过的令牌名供调用方记账清理。 */
export function applyColorOverrides(root: HTMLElement, mode: ResolvedMode): string[] {
  const entries = readColorOverrides()[mode] ?? {}
  const written: string[] = []
  for (const [token, value] of Object.entries(entries)) {
    if (!isColorToken(token) || !colorHex.test(value)) continue
    if (root.style.getPropertyValue(token) !== value) root.style.setProperty(token, value)
    written.push(token)
  }
  return written
}

/**
 * 未覆盖时读主题自己的取值：色块与十六进制输入都以它起稿。
 * 令牌可能是 `color-mix()` 这类表达式，交给浏览器解析一次再取 RGB。
 */
export function currentColorValue(token: string): string | undefined {
  if (typeof document === 'undefined') return undefined
  const declared = getComputedStyle(document.documentElement).getPropertyValue(token)
  const direct = toHexColor(declared)
  if (direct) return direct
  if (!declared.trim() || typeof document.body === 'undefined') return undefined
  const probe = document.createElement('span')
  probe.style.cssText = 'position:absolute;visibility:hidden;pointer-events:none'
  probe.style.backgroundColor = declared
  document.body.appendChild(probe)
  const resolved = toHexColor(getComputedStyle(probe).backgroundColor)
  probe.remove()
  return resolved
}
