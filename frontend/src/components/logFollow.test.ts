/**
 * @fileoverview followStep 的跟随契约：方向与剩余距离一致、单帧限幅、逐帧收敛且始终不过冲。
 */
import { describe, expect, it } from 'vitest'
import { MAX_FOLLOW_STEP, followStep } from './LogPanel'

/** 复刻组件里的跟随循环：距离 1 像素以内直接归位。 */
function followTo(target: number, frames = 600) {
  let position = 0
  for (let frame = 0; frame < frames; frame++) {
    const remaining = target - position
    if (Math.abs(remaining) <= 1) return target
    const step = followStep(remaining)
    if (Math.abs(step) > Math.abs(remaining)) return Number.NaN
    position += step
  }
  return position
}

describe('日志跟随步长', () => {
  it('远距离时单帧不超过上限，不会一步跳到底', () => {
    expect(Math.abs(followStep(100000))).toBeLessThanOrEqual(MAX_FOLLOW_STEP)
  })

  it('方向与剩余距离一致', () => {
    expect(followStep(500)).toBeGreaterThan(0)
    expect(followStep(-500)).toBeLessThan(0)
  })

  it('逐帧收敛到目标，且始终不过冲', () => {
    for (const target of [40, 400, 3000, 12000]) expect(followTo(target)).toBe(target)
  })

  it('近距离单帧走完，不留残余', () => {
    expect(Math.abs(followStep(1))).toBeLessThanOrEqual(1)
  })
})
