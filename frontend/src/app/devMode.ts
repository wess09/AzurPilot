/**
 * @fileoverview 开发者模式开关状态与连击激活触发逻辑。
 */

const DEV_MODE_KEY = 'azurpilot.dev-mode'
const DEV_CLICK_INTERVAL_MS = 900
const DEV_CLICK_TARGET = 10

let logoClickCount = 0
let lastLogoClickAt = 0

/** 开发者模式是否开启；存储不可用或未开启时返回 false。 */
export function readDevMode() {
  try { return window.localStorage.getItem(DEV_MODE_KEY) === '1' } catch { return false }
}

/** 写入或清除开发者模式标记，供设置变化时持久化。 */
export function writeDevMode(enabled: boolean) {
  try {
    if (enabled) window.localStorage.setItem(DEV_MODE_KEY, '1')
    else window.localStorage.removeItem(DEV_MODE_KEY)
  } catch { /* 存储不可用时仅当前会话生效。 */ }
}

/**
 * 记录一次 logo 点击：900ms 内连点满 10 次返回 true 并清零计数，否则返回 false。
 * 连点 logo 是隐藏的开发者模式入口，不设任何可见按钮。
 */
export function recordDevLogoClick(now = Date.now()) {
  logoClickCount = now - lastLogoClickAt <= DEV_CLICK_INTERVAL_MS ? logoClickCount + 1 : 1
  lastLogoClickAt = now
  if (logoClickCount < DEV_CLICK_TARGET) return false
  logoClickCount = 0
  lastLogoClickAt = 0
  return true
}

/** 清空连击计数，重新开始累计。 */
export function resetDevLogoClicks() {
  logoClickCount = 0
  lastLogoClickAt = 0
}
