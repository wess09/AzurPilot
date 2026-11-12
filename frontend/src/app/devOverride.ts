/**
 * @fileoverview 开发者工具的模拟状态覆盖（实例状态徽章、更新角标等）。
 */

import { useSyncExternalStore } from 'react'
import type { Status } from '../api/types'

/**
 * 开发者工具的「模拟状态」：把实例状态徽章与更新角标临时强制成某个值，到时自动恢复。
 *
 * 只影响显式声明 `simulate` 的状态徽章（实例卡）与更新角标，不碰真实数据，
 * 也不影响开发者工具页自己的控件预览。
 */
interface DevOverride {status: Status | null; updatePreview: boolean}

const OFF: DevOverride = {status: null, updatePreview: false}
const SERVER_SNAPSHOT = () => OFF
let snapshot: DevOverride = OFF
let timer: ReturnType<typeof setTimeout> | null = null
const listeners = new Set<() => void>()

function publish(next: DevOverride) {
  snapshot = next
  listeners.forEach(listener => listener())
}

const getDevOverride = () => snapshot
const subscribeDevOverride = (listener: () => void) => {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}
/** 订阅当前模拟状态：未模拟时 `status` 为 null、`updatePreview` 为 false。 */
export const useDevOverride = () => useSyncExternalStore(subscribeDevOverride, getDevOverride, SERVER_SNAPSHOT)

function stopTimer() {
  if (timer) {clearTimeout(timer); timer = null}
}

/** 模拟某个状态图标，`seconds` 秒后自动恢复；传 null 立即恢复。 */
export function simulateStatus(status: Status | null, seconds = 10) {
  stopTimer()
  publish({...snapshot, status})
  if (status) timer = setTimeout(() => {timer = null; publish({...snapshot, status: null})}, seconds * 1000)
}

/** 开关侧栏的「有新版本」更新角标预览，不必真等一次更新就能查看样式（开发者工具页的切换按钮在用）。 */
export function previewUpdate(active: boolean) {
  publish({...snapshot, updatePreview: active})
}

