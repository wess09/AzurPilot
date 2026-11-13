/**
 * @fileoverview 旧版总览页主区域显示模式（日志或资源统计）偏好。
 */

import { prefStore } from './prefStore'

/**
 * 旧版总览页主区显示什么。
 *
 * `logs` —— 默认。实例的运行日志。
 * `stats` —— 资源统计，与统计页同一套内容。
 *
 * 与其它界面偏好一张存法：关掉再打开接着上次的样子，直到用户自己切回去。
 */
type OverviewPanel = 'logs' | 'stats'

const store = prefStore<OverviewPanel>('azurpilot.legacy-overview-panel', raw => raw === 'stats' ? 'stats' : 'logs')

export const readOverviewPanel = store.read
export const subscribeOverviewPanel = store.subscribe
export const setOverviewPanel = store.write
