/**
 * @fileoverview 仪表盘资源卡排布、疏密与行动力口径等外观偏好持久化。
 */

/**
 * 仪表盘外观偏好：资源卡的排布、疏密、字号与行动力口径。
 *
 * 与其它界面偏好一张存法：关掉再打开接着上次的样子，直到用户自己切回去。
 * 只存本浏览器，不区分实例。
 */
export interface DashboardPrefs {
  fitCards: boolean
  fitText: boolean
  dense: boolean
  merged: boolean
  totalFirst: boolean
  dogIcon: boolean
}

const PREFS_KEY = 'azurpilot.dashboard'
const PREFS_DEFAULTS: DashboardPrefs = {fitCards: false, fitText: false, dense: false, merged: false, totalFirst: false, dogIcon: true}
const listeners = new Set<() => void>()

function read(): DashboardPrefs {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(PREFS_KEY) ?? 'null')
    if (saved && typeof saved === 'object') {
      const result = {...PREFS_DEFAULTS}
      for (const key of Object.keys(PREFS_DEFAULTS) as (keyof DashboardPrefs)[]) {
        if (typeof (saved as Record<string, unknown>)[key] === 'boolean') result[key] = (saved as DashboardPrefs)[key]
      }
      return result
    }
  } catch { /* 损坏偏好沿用默认值。 */ }
  return PREFS_DEFAULTS
}

let snapshot: DashboardPrefs = read()

/** 读取当前偏好快照，配 useSyncExternalStore 作 getSnapshot 使用。 */
export function readDashboardPrefs() {
  return snapshot
}

/** 订阅偏好变化，返回取消订阅函数。 */
export const subscribeDashboardPrefs = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

/** 切换单个偏好开关并广播变更；落盘尽力而为，失败不影响本会话。 */
export function setDashboardPref(key: keyof DashboardPrefs, enabled: boolean) {
  snapshot = {...snapshot, [key]: enabled}
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(snapshot)) } catch { /* 存储不可用时本次会话内仍生效。 */ }
  listeners.forEach(listener => listener())
}
