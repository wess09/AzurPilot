import { describe, expect, it } from 'vitest'
import { routeDepth, routeDirection, triggerCardStaggerMotion } from './pageMotion'
import { calculateCardDiagonalScore, calculateNonLinearDelay, sortCardsFromTopLeft } from './cardMotion'

describe('routeDepth', () => {
  it('按路径段数计算深度', () => {
    expect(routeDepth('/')).toBe(0)
    expect(routeDepth('/settings')).toBe(1)
    expect(routeDepth('/i/demo-main/overview')).toBe(3)
    expect(routeDepth('/i/demo-main/task/Alas')).toBe(4)
  })
})

describe('routeDirection', () => {
  it('深入实例为 forward，返回为 back', () => {
    expect(routeDirection('/', '/i/demo-main/overview')).toBe('forward')
    expect(routeDirection('/i/demo-main/overview', '/')).toBe('back')
    expect(routeDirection('/interface', '/i/demo-main/statistics')).toBe('forward')
  })

  it('顶层导航按侧栏顺序判断横向方向', () => {
    expect(routeDirection('/interface', '/settings')).toBe('forward')
    expect(routeDirection('/settings', '/interface')).toBe('back')
    expect(routeDirection('/updater', '/configs')).toBe('forward')
  })

  it('实例内一级页按 总览→统计 的方向', () => {
    expect(routeDirection('/i/a/overview', '/i/a/statistics')).toBe('forward')
    expect(routeDirection('/i/a/statistics', '/i/a/overview')).toBe('back')
  })

  it('无法判定方向时用淡入（任务参数切换、切换实例）', () => {
    expect(routeDirection('/i/a/task/Alas', '/i/a/task/Daily')).toBe('fade')
    expect(routeDirection('/i/a/overview', '/i/b/overview')).toBe('fade')
    expect(routeDirection('/settings', '/updater')).toBe('back')
  })
})

describe('cardMotion（卡片从左上角逐个错峰上浮算法）', () => {
  const rootRect = { left: 100, top: 50 }

  it('计算左上角几何对角线投影得分：Score = Y + X * 0.65', () => {
    // 处于根容器左上角原点。
    expect(calculateCardDiagonalScore({ left: 100, top: 50 }, rootRect)).toBe(0)
    // 同一行（Y 相同），右侧卡片得分高于左侧。
    const scoreLeft = calculateCardDiagonalScore({ left: 100, top: 50 }, rootRect)
    const scoreRight = calculateCardDiagonalScore({ left: 300, top: 50 }, rootRect)
    expect(scoreRight).toBeGreaterThan(scoreLeft)
    expect(scoreRight).toBe(200 * 0.65)
    // 同一列（X 相同），下方卡片得分高于上方。
    const scoreBottom = calculateCardDiagonalScore({ left: 100, top: 200 }, rootRect)
    expect(scoreBottom).toBe(150)
  })

  it('网格布局下依「左上角向右下角」对角线波纹顺序排序', () => {
    const mockRoot = { getBoundingClientRect: () => ({ left: 0, top: 0 }) } as unknown as HTMLElement

    const cardTopLeft = { getBoundingClientRect: () => ({ left: 0, top: 0 }), id: 'top-left' } as unknown as HTMLElement
    const cardTopRight = { getBoundingClientRect: () => ({ left: 200, top: 0 }), id: 'top-right' } as unknown as HTMLElement
    const cardBottomLeft = { getBoundingClientRect: () => ({ left: 0, top: 150 }), id: 'bottom-left' } as unknown as HTMLElement
    const cardBottomRight = { getBoundingClientRect: () => ({ left: 200, top: 150 }), id: 'bottom-right' } as unknown as HTMLElement

    // 打乱顺序传入。
    const shuffled = [cardBottomRight, cardTopRight, cardBottomLeft, cardTopLeft]
    const sorted = sortCardsFromTopLeft(shuffled, mockRoot)

    expect(sorted).toEqual([cardTopLeft, cardTopRight, cardBottomLeft, cardBottomRight])
  })

  it('单列与单行布局保持直观方向', () => {
    const mockRoot = { getBoundingClientRect: () => ({ left: 0, top: 0 }) } as unknown as HTMLElement

    // 单行横向（如 Overview 资源卡片）。
    const r1 = { getBoundingClientRect: () => ({ left: 0, top: 10 }) } as unknown as HTMLElement
    const r2 = { getBoundingClientRect: () => ({ left: 120, top: 10 }) } as unknown as HTMLElement
    const r3 = { getBoundingClientRect: () => ({ left: 240, top: 10 }) } as unknown as HTMLElement
    expect(sortCardsFromTopLeft([r3, r1, r2], mockRoot)).toEqual([r1, r2, r3])

    // 单列竖排（如 TaskConfig 各配置组）。
    const c1 = { getBoundingClientRect: () => ({ left: 10, top: 0 }) } as unknown as HTMLElement
    const c2 = { getBoundingClientRect: () => ({ left: 10, top: 100 }) } as unknown as HTMLElement
    const c3 = { getBoundingClientRect: () => ({ left: 10, top: 200 }) } as unknown as HTMLElement
    expect(sortCardsFromTopLeft([c3, c2, c1], mockRoot)).toEqual([c1, c2, c3])
  })

  it('非线性延迟算法：首个卡片为 0，后续卡片按 Ease-Out 曲线平滑收敛，打破机械等距', () => {
    // 只有一个卡片或首个卡片。
    expect(calculateNonLinearDelay(0, 1)).toBe(0)
    expect(calculateNonLinearDelay(0, 5)).toBe(0)

    // 少量卡片保持清晰步长。
    expect(calculateNonLinearDelay(1, 3)).toBe(34)
    expect(calculateNonLinearDelay(2, 3)).toBe(68)

    // 多个卡片（如 5 个卡片），步长呈现非线性自然递减收敛。
    const d0 = calculateNonLinearDelay(0, 5)
    const d1 = calculateNonLinearDelay(1, 5)
    const d2 = calculateNonLinearDelay(2, 5)
    const d3 = calculateNonLinearDelay(3, 5)
    const d4 = calculateNonLinearDelay(4, 5)

    expect(d0).toBe(0)
    expect(d4).toBe(170)
    const step1 = d1 - d0
    const step2 = d2 - d1
    const step3 = d3 - d2
    const step4 = d4 - d3

    // 步长递减，形成先清晰后收敛的自然物理水波。
    expect(step1).toBeGreaterThanOrEqual(step2)
    expect(step2).toBeGreaterThanOrEqual(step3)
    expect(step3).toBeGreaterThanOrEqual(step4)
  })

  it('环境安全：无 DOM 环境下调用 trigger 不抛错', () => {
    expect(() => triggerCardStaggerMotion(null)).not.toThrow()
  })
})
