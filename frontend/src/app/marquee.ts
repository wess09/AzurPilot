/**
 * @fileoverview 超长任务标题跑马灯滚动计算与同步逻辑。
 */

import { motionReducedActive, motionSpeedValue } from './motionPrefs'

/** 两份文案之间的空隙：滚动时它把两份分开，接缝因此看不出来。 */
export const MARQUEE_GAP = 8
/** 滚动速度（像素/秒）。时长由位移算出来，字数多的标题不会慢得离谱。 */
const MARQUEE_SPEED = 40
/** 时长下限：只溢出一两个字时也要看得清。 */
const MARQUEE_MIN_SECONDS = 6

type MarqueePlan = { scrolling: boolean; shift: number; duration: number }

/** 位移取「一份文案宽 + 空隙」：滚过这一段，第二份正好落到第一份的位置，循环看不出接缝。 */
export function marqueePlan(options: {
  copyWidth: number
  containerWidth: number
  gap: number
  speed: number
  reduced: boolean
}): MarqueePlan {
  const { copyWidth, containerWidth, gap, speed, reduced } = options
  const shift = Math.max(0, copyWidth) + Math.max(0, gap)
  /* 宽度按取整后的像素比，允许 1px 误差，避免半像素宽度把刚好放得下的标题判成溢出。 */
  if (reduced || copyWidth <= containerWidth + 1 || shift <= 0) return { scrolling: false, shift: 0, duration: 0 }
  return { scrolling: true, shift, duration: Math.max(MARQUEE_MIN_SECONDS, shift / MARQUEE_SPEED) * (speed / 2) }
}

/** 把灯带状态写进 DOM：标记落在容器上，位移/空隙/时长三个变量交给 CSS 消费。
 * 返回是否在滚，调用方据此决定要不要放第二份文案。 */
export function syncMarquee(container: HTMLElement | null, copy: HTMLElement | null): boolean {
  if (!container || !copy) return false
  const track = copy.parentElement
  const gap = parseFloat(getComputedStyle(track ?? container).columnGap) || MARQUEE_GAP
  const plan = marqueePlan({
    copyWidth: copy.getBoundingClientRect().width,
    containerWidth: container.clientWidth,
    gap,
    speed: motionSpeedValue(),
    reduced: motionReducedActive(),
  })
  if (!plan.scrolling) {
    delete container.dataset.marquee
    container.style.removeProperty('--marquee-shift')
    container.style.removeProperty('--marquee-duration')
    return false
  }
  container.dataset.marquee = 'on'
  container.style.setProperty('--marquee-gap', `${gap}px`)
  container.style.setProperty('--marquee-shift', `${plan.shift}px`)
  container.style.setProperty('--marquee-duration', `${plan.duration}s`)
  return true
}
