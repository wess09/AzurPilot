/**
 * @fileoverview 页面层级路由转场动效推断与执行。
 */

import { useLayoutEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { motionReducedActive, motionSpeedValue } from './motionPrefs'
import { triggerCardStaggerMotion } from './cardMotion'

export { triggerCardStaggerMotion } from './cardMotion'

type NavDirection = 'forward' | 'back' | 'fade'

// 侧栏顶层导航的展示顺序：同深度页面之间用它判断横向方向（向右 = forward）。
const PRIMARY_NAV_ORDER = ['/updater', '/interface', '/remote', '/configs', '/settings']
// 实例内一级页的展示顺序：与顶层导航一样用于同深度互跳的横向方向判断；
// 这些页挂在实例路径前缀之下，orderIndex 对本表改用 endsWith 匹配。
const INSTANCE_PAGE_ORDER = ['/overview', '/resources', '/statistics']

export function routeDepth(pathname: string): number {
  return pathname.split('/').filter(Boolean).length
}

function orderIndex(pathname: string, order: readonly string[]): number {
  if (order === INSTANCE_PAGE_ORDER) return order.findIndex(item => pathname.endsWith(item))
  return order.indexOf(pathname)
}

/**
 * 依据「深度变化 → 纵向层级；同深度 → 导航顺序」推断转场方向。
 * 深度增加 = forward（自右滑入）；深度减少 = back（自左滑入）；
 * 无法判定时 fade（如切换任务参数、切换实例）。
 */
export function routeDirection(from: string, to: string): NavDirection {
  const depthFrom = routeDepth(from)
  const depthTo = routeDepth(to)
  if (depthTo > depthFrom) return 'forward'
  if (depthTo < depthFrom) return 'back'
  const primaryFrom = orderIndex(from, PRIMARY_NAV_ORDER)
  const primaryTo = orderIndex(to, PRIMARY_NAV_ORDER)
  if (primaryFrom >= 0 && primaryTo >= 0 && primaryFrom !== primaryTo) return primaryTo > primaryFrom ? 'forward' : 'back'
  const instanceFrom = orderIndex(from, INSTANCE_PAGE_ORDER)
  const instanceTo = orderIndex(to, INSTANCE_PAGE_ORDER)
  if (instanceFrom >= 0 && instanceTo >= 0 && instanceFrom !== instanceTo) return instanceTo > instanceFrom ? 'forward' : 'back'
  return 'fade'
}

const DIRECTION_CLASS: Record<NavDirection, string> = {
  forward: 'motion-nav-forward',
  back: 'motion-nav-back',
  fade: 'motion-nav-fade',
}

const ALL_CLASSES = ['motion-nav-forward', 'motion-nav-back', 'motion-nav-fade']

let cleanupTimer: number | null = null

function stopTransition(target: HTMLElement) {
  if (cleanupTimer !== null) window.clearTimeout(cleanupTimer)
  cleanupTimer = null
  target.classList.remove(...ALL_CLASSES)
}

function playTransition(target: HTMLElement, className: string) {
  stopTransition(target)
  void target.offsetWidth
  target.classList.add(className)
  cleanupTimer = window.setTimeout(() => {
    target.classList.remove(className)
    cleanupTimer = null
  }, 480 * motionSpeedValue())
}

/**
 * 给 #main-content 挂页面转场类，并调度卡片从左上角逐个错峰上浮。
 * - 系统「减少动效」或调试模拟开启时直接跳过；
 * - 页面进入与异步数据挂载卡片时，依物理几何坐标逐个上浮；
 * - 用 useLayoutEffect 在绘制前挂类，避免闪帧。
 */
export function usePageMotion() {
  const location = useLocation()
  const previous = useRef<string | null>(null)
  useLayoutEffect(() => {
    const pathname = location.pathname
    const target = document.getElementById('main-content')
    const before = previous.current
    previous.current = pathname
    if (!target) return
    if (motionReducedActive()) return

    triggerCardStaggerMotion(target)

    if (before === null || before === pathname) return
    const className = DIRECTION_CLASS[routeDirection(before, pathname)]
    playTransition(target, className)
    return () => stopTransition(target)
  }, [location.pathname])
}
