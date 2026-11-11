// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('./motionPrefs', () => ({
  motionReducedActive: () => false,
  motionSpeedValue: () => 1,
}))

import { applyCardStaggerMotion } from './cardMotion'

afterEach(() => vi.restoreAllMocks())

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

  it('只跳过含开关且使用背景模糊的任务卡片', () => {
    const glassWithSwitch = document.createElement('section')
    glassWithSwitch.className = 'config-group'
    glassWithSwitch.innerHTML = '<button data-slot="switch"></button>'
    const plainWithSwitch = glassWithSwitch.cloneNode(true) as HTMLElement
    const glassWithoutSwitch = document.createElement('section')
    glassWithoutSwitch.className = 'config-group'
    vi.spyOn(window, 'getComputedStyle').mockImplementation(element => ({
      backdropFilter: element === plainWithSwitch ? 'none' : 'blur(18px)',
    }) as CSSStyleDeclaration)

    applyCardStaggerMotion([glassWithSwitch, plainWithSwitch, glassWithoutSwitch], 2)

    expect(glassWithSwitch.classList.contains('motion-card-stagger')).toBe(false)
    expect(plainWithSwitch.classList.contains('motion-card-stagger')).toBe(true)
    expect(glassWithoutSwitch.classList.contains('motion-card-stagger')).toBe(true)
  })
})
