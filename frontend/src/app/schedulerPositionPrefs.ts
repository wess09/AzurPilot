/**
 * @fileoverview 总览页页调度器放置位置（左侧或右侧）偏好管理与持久化。
 */

import { prefStore } from './prefStore'

/** 总览页调度器栏停靠位置。 */
export type SchedulerPosition = 'left' | 'right'

const store = prefStore<SchedulerPosition>(
  'azurpilot.layout.scheduler-position',
  raw => raw === 'right' ? 'right' : 'left'
)

/** 读取调度器栏停靠位置。 */
export const readSchedulerPosition = store.read
/** 订阅调度器栏停靠位置变化，返回退订函数。 */
export const subscribeSchedulerPosition = store.subscribe
/** 写入并持久化调度器栏停靠位置。 */
export const setSchedulerPosition = store.write
