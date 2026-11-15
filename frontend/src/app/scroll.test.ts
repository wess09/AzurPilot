/**
 * @fileoverview 平滑滚动辅助函数的行为回归测试。
 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { animateScrollTop, easeOutCubic, scrollTargetTop, smoothScrollToElement } from './scroll'

afterEach(() => vi.unstubAllGlobals())

describe('easeOutCubic', () => {
  it('端点精确、前段快后段慢', () => {
    expect(easeOutCubic(0)).toBe(0)
    expect(easeOutCubic(1)).toBe(1)
    expect(easeOutCubic(0.5)).toBeGreaterThan(0.5)
    expect(easeOutCubic(0.5)).toBeCloseTo(0.875, 3)
  })
})

describe('scrollTargetTop', () => {
  it('含 scroll-margin-top', () => {
    expect(scrollTargetTop(0, 0, 500, 85, 2000)).toBe(415)
  })
  it('夹取上下边界', () => {
    expect(scrollTargetTop(0, 0, 50, 85, 2000)).toBe(0)
    expect(scrollTargetTop(0, 0, 5000, 0, 2000)).toBe(2000)
    expect(scrollTargetTop(1200, 0, 300, 0, 2000)).toBe(1500)
  })
  it('容器不可滚动时归零', () => {
    expect(scrollTargetTop(0, 0, 500, 0, -50)).toBe(0)
  })
})

describe('animateScrollTop', () => {
  it('同一容器开始新滚动时取消上一帧任务', () => {
    let nextFrame = 1
    const cancelled: number[] = []
    vi.stubGlobal('requestAnimationFrame', vi.fn(() => nextFrame++))
    vi.stubGlobal('cancelAnimationFrame', vi.fn((frame: number) => cancelled.push(frame)))
    // node 环境没有真元素：用 EventTarget 充当容器，它自带 add/removeEventListener，滚动位置就是挂上去的普通字段。
    const container = Object.assign(new EventTarget(), {scrollTop: 0}) as HTMLElement

    animateScrollTop(container, 100, 280)
    animateScrollTop(container, 200, 280)

    expect(cancelled).toEqual([1])
  })
})

describe('smoothScrollToElement', () => {
  it('文档滚动后重复点击同一锚点不会继续下滑', () => {
    const scroller = Object.assign(new EventTarget(), {
      scrollTop: 0,
      scrollHeight: 2000,
      clientHeight: 500,
      getBoundingClientRect: () => ({top: -scroller.scrollTop}),
    }) as HTMLElement
    const target = {
      parentElement: null,
      getBoundingClientRect: () => ({top: 600 - scroller.scrollTop}),
    } as HTMLElement
    // 桩掉 document 与 getComputedStyle：目标没有可滚动父级，走文档滚动路径，scroll-margin 读作 0。
    vi.stubGlobal('document', {scrollingElement: scroller})
    vi.stubGlobal('getComputedStyle', () => ({scrollMarginTop: '0px'}))

    smoothScrollToElement(target)
    expect(scroller.scrollTop).toBe(600)
    smoothScrollToElement(target)
    expect(scroller.scrollTop).toBe(600)
  })
})
