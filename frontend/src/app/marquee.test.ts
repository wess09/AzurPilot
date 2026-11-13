/**
 * @fileoverview marqueePlan 的契约测试：守住 1px 容差、无缝接上的位移量、时长随倍率缩放与减少动态时停滚。
 */
import { describe, expect, it } from 'vitest'
import { MARQUEE_GAP, marqueePlan } from './marquee'

const base = { gap: MARQUEE_GAP, speed: 2, reduced: false }

describe('任务标题的灯带滚动', () => {
  it('放得下的标题不滚', () => {
    expect(marqueePlan({ ...base, copyWidth: 80, containerWidth: 120 }).scrolling).toBe(false)
  })

  it('刚好超出 1px 仍算放得下，再多 1px 才滚', () => {
    expect(marqueePlan({ ...base, copyWidth: 121, containerWidth: 120 }).scrolling).toBe(false)
    expect(marqueePlan({ ...base, copyWidth: 122, containerWidth: 120 }).scrolling).toBe(true)
  })

  it('位移等于一份文案宽加空隙，第二份才能无缝接上', () => {
    const plan = marqueePlan({ ...base, copyWidth: 200, containerWidth: 120 })
    expect(plan.shift).toBe(200 + MARQUEE_GAP)
  })

  it('时长随动效倍率缩放：倍率 1 是基准的一半', () => {
    const normal = marqueePlan({ ...base, copyWidth: 200, containerWidth: 120 })
    const fast = marqueePlan({ ...base, copyWidth: 200, containerWidth: 120, speed: 1 })
    expect(normal.duration).toBeGreaterThan(0)
    expect(fast.duration).toBeCloseTo(normal.duration / 2)
  })

  it('减少动态效果时不滚', () => {
    expect(marqueePlan({ ...base, copyWidth: 200, containerWidth: 120, reduced: true }).scrolling).toBe(false)
  })
})
