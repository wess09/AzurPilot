/**
 * @fileoverview 全局动效偏好：JS 侧速度倍率与「减少动效」判定（简约主题 / 系统设置）。
 */

const browser = typeof window !== 'undefined' && typeof document !== 'undefined'

/** 简约主题与系统「减少动效」设置都会关闭装饰动效。 */
export const motionReducedActive = () =>
  !browser || document.documentElement.dataset.theme === 'minimal' ||
  (typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches)

/** 当前速度倍率：用于 JS 侧计时（如转场类清理定时器、卡片错峰延迟）；固定 2＝时长统一翻倍。 */
export const motionSpeedValue = () => 2
