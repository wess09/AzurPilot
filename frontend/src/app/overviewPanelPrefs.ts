/**
 * @fileoverview 总览页主区域显示模式（日志或资源统计）偏好。
 */

import { prefStore } from './prefStore'

/**
 * 总览页主区显示什么。
 *
 * `logs` —— 默认。实例的运行日志。
 * `stats` —— 资源统计，与统计页同一套内容。
 *
 * 与其它界面偏好一张存法：关掉再打开接着上次的样子，直到用户自己切回去。
 */
type OverviewPanel = 'logs' | 'stats'

const store = prefStore<OverviewPanel>('azurpilot.overview-panel', raw => raw === 'stats' ? 'stats' : 'logs')

// 键名来自旧版命名，首次读取时迁移到新键；重置没有清键路径，迁移一次即可。
try {
  if (localStorage.getItem('azurpilot.overview-panel') == null) {
    const migrated = localStorage.getItem('azurpilot.legacy-overview-panel')
    if (migrated != null) {
      localStorage.setItem('azurpilot.overview-panel', migrated)
      localStorage.removeItem('azurpilot.legacy-overview-panel')
    }
  }
} catch { /* 存储不可用时跳过迁移，本次会话内按默认值工作。 */ }

export const readOverviewPanel = store.read
/** 订阅总览主区显示模式变化，返回退订函数。 */
export const subscribeOverviewPanel = store.subscribe
/** 写入并持久化总览主区显示模式。 */
export const setOverviewPanel = store.write
