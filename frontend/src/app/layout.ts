/**
 * @fileoverview 侧栏收起（看图模式）与自定义宽度状态、调度器栏自定义宽度状态：全页面共享、持久化。
 */

const SIDEBAR_KEY = 'azurpilot.layout.sidebar'
const SIDEBAR_WIDTH_KEY = 'azurpilot.layout.sidebar-width'
const LEGACY_RAIL_WIDTH_KEY = 'azurpilot.layout.legacy-rail-width'

export const SIDEBAR_WIDTH_MIN = 150
export const SIDEBAR_WIDTH_MAX = 520

export const LEGACY_RAIL_WIDTH_MIN = 220
export const LEGACY_RAIL_WIDTH_MAX = 560
export const LEGACY_RAIL_WIDTH_DEFAULT = 280

const readCollapsed = (key: string) => {
  try { return localStorage.getItem(key) === '1' } catch { return false }
}

const readWidth = (): number | null => {
  try {
    const raw = localStorage.getItem(SIDEBAR_WIDTH_KEY)
    if (!raw) return null
    const num = Number(raw)
    if (Number.isFinite(num) && num >= SIDEBAR_WIDTH_MIN && num <= SIDEBAR_WIDTH_MAX) {
      return num
    }
    return null
  } catch { return null }
}

const readRailWidth = (): number | null => {
  try {
    const raw = localStorage.getItem(LEGACY_RAIL_WIDTH_KEY)
    if (!raw) return null
    const num = Number(raw)
    if (Number.isFinite(num) && num >= LEGACY_RAIL_WIDTH_MIN && num <= LEGACY_RAIL_WIDTH_MAX) {
      return num
    }
    return null
  } catch { return null }
}

export interface LayoutState {
  /** 侧栏是否收起：全页面有效。 */
  sidebarCollapsed: boolean
  /** 侧栏自定义宽度（像素，null 表示遵循主题默认宽度）：全页面有效。 */
  sidebarWidth: number | null
  /** 旧版总览页左列调度器栏自定义宽度（像素，null 表示遵循默认宽度）：持久化。 */
  legacyRailWidth: number | null
}

let state: LayoutState = {
  sidebarCollapsed: readCollapsed(SIDEBAR_KEY),
  sidebarWidth: readWidth(),
  legacyRailWidth: readRailWidth(),
}
const listeners = new Set<() => void>()

export const getLayout = () => state

export function subscribeLayout(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

function publish(patch: Partial<LayoutState>) {
  state = {...state, ...patch}
  try {
    localStorage.setItem(SIDEBAR_KEY, state.sidebarCollapsed ? '1' : '0')
    if (state.sidebarWidth != null) {
      localStorage.setItem(SIDEBAR_WIDTH_KEY, String(state.sidebarWidth))
    } else {
      localStorage.removeItem(SIDEBAR_WIDTH_KEY)
    }
    if (state.legacyRailWidth != null) {
      localStorage.setItem(LEGACY_RAIL_WIDTH_KEY, String(state.legacyRailWidth))
    } else {
      localStorage.removeItem(LEGACY_RAIL_WIDTH_KEY)
    }
  } catch { /* 存储不可用时只在本次会话生效，不影响使用。 */ }
  listeners.forEach(listener => listener())
}

export const setSidebarCollapsed = (value: boolean) => publish({sidebarCollapsed: value})

export const setSidebarWidth = (width: number | null) => {
  if (width == null) {
    publish({sidebarWidth: null})
    return
  }
  const maxAllowed = typeof window !== 'undefined'
    ? Math.min(SIDEBAR_WIDTH_MAX, Math.round(window.innerWidth * 0.5))
    : SIDEBAR_WIDTH_MAX
  const clamped = Math.max(SIDEBAR_WIDTH_MIN, Math.min(Math.round(width), maxAllowed))
  publish({sidebarWidth: clamped})
}

export const resetSidebarWidth = () => publish({sidebarWidth: null})

export const setLegacyRailWidth = (width: number | null) => {
  if (width == null) {
    publish({legacyRailWidth: null})
    return
  }
  const maxAllowed = typeof window !== 'undefined'
    ? Math.min(LEGACY_RAIL_WIDTH_MAX, Math.round(window.innerWidth * 0.6))
    : LEGACY_RAIL_WIDTH_MAX
  const clamped = Math.max(LEGACY_RAIL_WIDTH_MIN, Math.min(Math.round(width), maxAllowed))
  publish({legacyRailWidth: clamped})
}

export const resetLegacyRailWidth = () => publish({legacyRailWidth: null})
