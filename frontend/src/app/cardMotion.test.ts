// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'

// 桩掉用户动效偏好：非减弱模式动画才会执行，速度固定为 1 让用例只考察清理时序本身。
vi.mock('./motionPrefs', () => ({
  motionReducedActive: () => false,
  motionSpeedValue: () => 1,
}))

import { applyCardStaggerMotion } from './cardMotion'

describe('卡片入场动画清理', () => {
  it('子元素动画先结束时，仍在卡片动画结束后清理变换', () => {
    const card = document.createElement('section')
    const child = document.createElement('span')
    card.appendChild(child)

    applyCardStaggerMotion([card], 1)
    child.dispatchEvent(new Event('animationend', {bubbles: true}))
    expect(card.classList.contains('motion-card-stagger')).toBe(true)

    card.dispatchEvent(new Event('animationend', {bubbles: true}))
    expect(card.classList.contains('motion-card-stagger')).toBe(false)
    expect(card.style.getPropertyValue('--card-stagger-delay')).toBe('')
  })
})
