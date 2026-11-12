/**
 * @fileoverview 旧版实例页右列偏好管理：调度器栏的显隐。
 *
 * 目录与调度器已经改为同栏并存，不再二选一；这里只保留栏本身的开关。
 * 停靠边沿用 schedulerPositionPrefs（运行总览与任务设置页共用同一个值）。
 */

import { prefStore } from './prefStore'

/** `shown` —— 默认，右列显示「目录 + 调度器」。`hidden` —— 整栏收起。 */
type RailVisibility = 'shown' | 'hidden'

const store = prefStore<RailVisibility>('azurpilot.legacy-rail-visible', raw => raw === 'hidden' ? 'hidden' : 'shown')

/** 读取右列显隐：存储不可用或存的值不是 'hidden' 时一律回落 'shown'。 */
export const readRailVisible = store.read
/** 订阅右列显隐变化，返回退订函数。 */
export const subscribeRailVisible = store.subscribe
/** 写入并持久化右列显隐，随后通知所有订阅者；存储不可用时仅本次会话生效。 */
export const setRailVisible = store.write
