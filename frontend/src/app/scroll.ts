/**
 * @fileoverview 平滑滚动辅助函数，支持自定义缓动与滚动边距计算。
 */

import { motionReducedActive } from './motionPrefs'

/** 缓动：起步快、收尾慢；与动效系统 decelerate 方言一致。 */
export function easeOutCubic(progress: number): number {
  return 1 - Math.pow(1 - progress, 3)
}

/** 计算目标元素应滚动到的 scrollTop（含 scroll-margin-top 与上下边界夹取）。纯函数，便于单测。 */
export function scrollTargetTop(
  containerScrollTop: number,
  containerRectTop: number,
  targetRectTop: number,
  scrollMarginTop: number,
  maxScrollTop: number,
): number {
  const raw = containerScrollTop + (targetRectTop - containerRectTop) - scrollMarginTop
  return Math.max(0, Math.min(raw, Math.max(0, maxScrollTop)))
}

function findScrollParent(element: HTMLElement): HTMLElement | null {
  let parent = element.parentElement
  while (parent) {
    const style = getComputedStyle(parent)
    if (/(auto|scroll|overlay)/.test(style.overflowY) && parent.scrollHeight > parent.clientHeight + 1) return parent
    parent = parent.parentElement
  }
  return null
}

function readScrollMarginTop(element: HTMLElement): number {
  const value = Number.parseFloat(getComputedStyle(element).scrollMarginTop)
  return Number.isFinite(value) ? value : 0
}

type ActiveScroll = {raf: number; cancel: () => void}
const activeScrolls = new WeakMap<HTMLElement, ActiveScroll>()

/** 把容器的 scrollTop 动画到目标值：同容器再次调用会取消进行中的动画；用户滚动输入（滚轮/触摸/按下）会立即中断动画交还控制权。 */
export function animateScrollTop(container: HTMLElement, to: number, duration: number) {
  activeScrolls.get(container)?.cancel()
  const from = container.scrollTop
  if (duration <= 0 || from === to) {
    container.scrollTop = to
    return
  }
  const start = performance.now()
  let active: ActiveScroll
  const stopOnUserInput = () => active.cancel()
  const cleanup = () => {
    container.removeEventListener('wheel', stopOnUserInput)
    container.removeEventListener('touchstart', stopOnUserInput)
    container.removeEventListener('pointerdown', stopOnUserInput)
    if (activeScrolls.get(container) === active) activeScrolls.delete(container)
  }
  const cancel = () => {
    if (active.raf) cancelAnimationFrame(active.raf)
    cleanup()
  }
  active = {raf: 0, cancel}
  activeScrolls.set(container, active)
  container.addEventListener('wheel', stopOnUserInput, {passive: true})
  container.addEventListener('touchstart', stopOnUserInput, {passive: true})
  container.addEventListener('pointerdown', stopOnUserInput, {passive: true})
  const step = (now: number) => {
    if (activeScrolls.get(container) !== active) return
    const progress = Math.min(1, (now - start) / duration)
    container.scrollTop = from + (to - from) * easeOutCubic(progress)
    if (progress < 1) active.raf = requestAnimationFrame(step)
    else cleanup()
  }
  active.raf = requestAnimationFrame(step)
}

/** 平滑滚动到目标元素。找不到可滚动祖先时回退到文档滚动。 */
export function smoothScrollToElement(target: HTMLElement, duration = 280) {
  const reduce = motionReducedActive()
  const container = findScrollParent(target)
  if (container) {
    const to = scrollTargetTop(
      container.scrollTop,
      container.getBoundingClientRect().top,
      target.getBoundingClientRect().top,
      readScrollMarginTop(target),
      container.scrollHeight - container.clientHeight,
    )
    animateScrollTop(container, to, reduce ? 0 : duration)
    return
  }
  const scroller = (document.scrollingElement as HTMLElement | null) ?? document.documentElement
  const to = scrollTargetTop(
    scroller.scrollTop,
    // 文档滚动的参照系是视口；documentElement 的矩形顶部会随滚动变成负数。
    0,
    target.getBoundingClientRect().top,
    readScrollMarginTop(target),
    scroller.scrollHeight - scroller.clientHeight,
  )
  animateScrollTop(scroller, to, reduce ? 0 : duration)
}
