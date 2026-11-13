import { describe, expect, it } from 'vitest'
import { motionReducedActive, motionSpeedValue } from './motionPrefs'

describe('motionPrefs（全局动效偏好）', () => {
  it('速度倍率固定为 2（时长统一翻倍）', () => {
    expect(motionSpeedValue()).toBe(2)
  })

  it('无 DOM 环境（node/SSR）下按「减少动效」处理', () => {
    // 模块在 node 环境导入时不应触碰 document；此用例能跑通即证明守卫有效。
    expect(motionReducedActive()).toBe(true)
  })
})
