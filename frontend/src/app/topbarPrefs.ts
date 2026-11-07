/**
 * @fileoverview 实例标签大小与历史路径偏好。
 */

export const TAB_SIZES = ['sm', 'md', 'lg', 'xl'] as const
export type TabSize = typeof TAB_SIZES[number]

const TAB_SIZE_KEY = 'azurpilot.topbar-tab-size'
const LAST_PATH_KEY = 'azurpilot.last-path'

const DEFAULT_TAB_SIZE: TabSize = 'lg'
let sessionTabSize: TabSize = DEFAULT_TAB_SIZE

/** 档位要落在 :root 上：顶栏高度与标签页尺寸都由这一处驱动。 */
function applyTabSize(size: TabSize) {
  document.documentElement.dataset.tabSize = size
}

/* 在首帧应用上次保存的档位。 */
applyTabSize(readTabSize())

const tabSizeListeners = new Set<() => void>()

/** 标签页档位：落盘并通知订阅者，下次打开接着上次的档位。 */
export function readTabSize(): TabSize {
  try {
    const stored = localStorage.getItem(TAB_SIZE_KEY)
    return stored === 'xs' ? 'sm' : TAB_SIZES.find(size => size === stored) ?? DEFAULT_TAB_SIZE
  } catch { return sessionTabSize }
}

export const subscribeTabSize = (listener: () => void) => {
  tabSizeListeners.add(listener)
  return () => { tabSizeListeners.delete(listener) }
}

export function setTabSize(size: TabSize) {
  sessionTabSize = size
  applyTabSize(size)
  try { localStorage.setItem(TAB_SIZE_KEY, size) } catch { /* 存储不可用时本次会话内仍生效。 */ }
  tabSizeListeners.forEach(listener => listener())
}

/** 上次停留的页面路径（如 `/configs` 或 `/i/ap/overview`）。
  记路径而不是实例：用户说的是「上次停在哪个界面，下次打开就回哪个界面」。 */
export function readLastPath(): string {
  try { return localStorage.getItem(LAST_PATH_KEY) ?? '' } catch { return '' }
}

export function writeLastPath(path: string) {
  try { localStorage.setItem(LAST_PATH_KEY, path) } catch { /* 存储不可用只影响下次启动的落点。 */ }
}
