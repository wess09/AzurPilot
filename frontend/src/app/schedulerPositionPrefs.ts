/**
 * @fileoverview 旧版总览页调度器放置位置（左侧或右侧）偏好管理与持久化。
 */

import { prefStore } from './prefStore'

export type SchedulerPosition = 'left' | 'right'

const store = prefStore<SchedulerPosition>(
  'azurpilot.layout.scheduler-position',
  raw => raw === 'right' ? 'right' : 'left'
)

export const readSchedulerPosition = store.read
export const subscribeSchedulerPosition = store.subscribe
export const setSchedulerPosition = store.write
