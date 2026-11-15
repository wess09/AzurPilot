/**
 * @fileoverview 侧栏收起（看图模式）与自定义宽度状态、调度器栏自定义宽度状态：全页面共享、持久化。
 */

const SIDEBAR_KEY = 'azurpilot.layout.sidebar'
const SIDEBAR_WIDTH_KEY = 'azurpilot.layout.sidebar-width'
const RAIL_WIDTH_KEY = 'azurpilot.layout.rail-width'
/** 重命名前的存储键：首次读取时迁移到新键，之后不再回头读。 */
const LEGACY_RAIL_WIDTH_KEY = 'azurpilot.layout.legacy-rail-width'

/** 侧栏自定义宽度下限（像素）。 */
export const SIDEBAR_WIDTH_MIN = 150
/** 侧栏自定义宽度上限（像素），实际写入时还会收到「视口一半」的约束。 */
export const SIDEBAR_WIDTH_MAX = 520

/** 总览页调度器栏宽度下限（像素）。 */
export const RAIL_WIDTH_MIN = 220
/** 调度器栏宽度上限（像素），实际写入时还会收到「视口 60%」的约束。 */
export const RAIL_WIDTH_MAX = 560
/** 调度器栏默认宽度（像素），未自定义或存储值无效时用它起稿。 */
export const RAIL_WIDTH_DEFAULT = 280

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
    const parse = (raw: string | null): number | null => {
      if (!raw) return null
      const num = Number(raw)
      return Number.isFinite(num) && num >= RAIL_WIDTH_MIN && num <= RAIL_WIDTH_MAX ? num : null
    }
    const current = parse(localStorage.getItem(RAIL_WIDTH_KEY))
    if (current != null) return current
    const migrated = parse(localStorage.getItem(LEGACY_RAIL_WIDTH_KEY))
    if (migrated != null) {
      localStorage.setItem(RAIL_WIDTH_KEY, String(migrated))
      localStorage.removeItem(LEGACY_RAIL_WIDTH_KEY)
    }
    return migrated
  } catch { return null }
}

interface LayoutState {
  /** 侧栏是否收起：全页面有效。 */
  sidebarCollapsed: boolean
  /** 侧栏自定义宽度（像素，null 表示遵循主题默认宽度）：全页面有效。 */
  sidebarWidth: number | null
  /** 总览页左列调度器栏自定义宽度（像素，null 表示遵循默认宽度）：持久化。 */
  railWidth: number | null
}

let state: LayoutState = {
  sidebarCollapsed: readCollapsed(SIDEBAR_KEY),
  sidebarWidth: readWidth(),
  railWidth: readRailWidth(),
}
const listeners = new Set<() => void>()

/** 读当前布局状态快照，供 useSyncExternalStore 的 getSnapshot 使用。 */
export const getLayout = () => state

/** 订阅布局变化，返回退订函数。 */
export function subscribeLayout(listener: () => void) {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

function publish(patch: Partial<LayoutState>) {
  if (Object.entries(patch).every(([key, value]) => state[key as keyof LayoutState] === value)) return
  state = {...state, ...patch}
  try {
    localStorage.setItem(SIDEBAR_KEY, state.sidebarCollapsed ? '1' : '0')
    if (state.sidebarWidth != null) {
      localStorage.setItem(SIDEBAR_WIDTH_KEY, String(state.sidebarWidth))
    } else {
      localStorage.removeItem(SIDEBAR_WIDTH_KEY)
    }
    if (state.railWidth != null) {
      localStorage.setItem(RAIL_WIDTH_KEY, String(state.railWidth))
    } else {
      localStorage.removeItem(RAIL_WIDTH_KEY)
    }
  } catch { /* 存储不可用时只在本次会话生效，不影响使用。 */ }
  listeners.forEach(listener => listener())
}

/** 切换侧栏收起（看图模式）并持久化。 */
export const setSidebarCollapsed = (value: boolean) => publish({sidebarCollapsed: value})

/** 将桌面侧栏宽度限制在固定边界与半个视口内。 */
export function clampSidebarWidth(width: number) {
  const maxAllowed = typeof window !== 'undefined'
    ? Math.min(SIDEBAR_WIDTH_MAX, Math.round(window.innerWidth * 0.5))
    : SIDEBAR_WIDTH_MAX
  return Math.max(SIDEBAR_WIDTH_MIN, Math.min(Math.round(width), maxAllowed))
}

/** 写入侧栏宽度（像素）并持久化，null 恢复主题默认。 */
export const setSidebarWidth = (width: number | null) => publish({sidebarWidth: width == null ? null : clampSidebarWidth(width)})

/** 恢复侧栏主题默认宽度并持久化。 */
export const resetSidebarWidth = () => publish({sidebarWidth: null})

/** 写入调度器栏宽度（像素）并持久化：按上下限与「视口 60%」收拢，null 恢复默认。 */
export const setModernRailWidth = (width: number | null) => {
  if (width == null) {
    publish({railWidth: null})
    return
  }
  const maxAllowed = typeof window !== 'undefined'
    ? Math.min(RAIL_WIDTH_MAX, Math.round(window.innerWidth * 0.6))
    : RAIL_WIDTH_MAX
  const clamped = Math.max(RAIL_WIDTH_MIN, Math.min(Math.round(width), maxAllowed))
  publish({railWidth: clamped})
}

/** 恢复调度器栏默认宽度并持久化。 */
export const resetModernRailWidth = () => publish({railWidth: null})
