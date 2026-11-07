/**
 * @fileoverview 页面卡片交错进场动效与拓扑排序计算。
 */

import { motionReducedActive, motionSpeedValue } from './motionPrefs'

/** 卡片选择器：涵盖总览、配置、统计、设置、更新等页面的核心卡片与面板。 */
const CARD_SELECTORS = [
  '.panel',
  '.resource-card',
  '.instance-card',
  '.statistics-table',
  '.statistics-chart',
  '.summary-metrics-panel',
  '.head-card',
  '.empty',
  '.error-box',
].join(', ')

/** 内部属性标记：记录卡片最近一次播放动画的会话 ID，避免在同一页面内重复播放。 */
const MOTION_SESSION_KEY = '__azurpilotCardMotionSession'

let currentSessionId = 0
let activeObserver: MutationObserver | null = null
let sessionTimeoutId: number | null = null

/**
 * 在根容器内查找所有顶层卡片元素。
 * 若存在嵌套卡片（例如大面板内包含子面板），只保留视觉顶层的独立卡片作为动效单元。
 */
export function findTopLevelCards(root: HTMLElement): HTMLElement[] {
  const allCards = Array.from(root.querySelectorAll<HTMLElement>(CARD_SELECTORS))
  return allCards.filter(card => {
    // 忽略不可见或尚未参与布局的元素
    if (card.offsetWidth === 0 && card.offsetHeight === 0 && card.getClientRects().length === 0) {
      return false
    }
    // 过滤掉祖先节点已是卡片的深层嵌套元素
    let parent = card.parentElement
    while (parent && parent !== root) {
      if (allCards.includes(parent)) return false
      parent = parent.parentElement
    }
    return true
  })
}

/**
 * 计算卡片相对于视口根容器左上角的对角线投影得分。
 * 公式：Score = Y + X * 0.65
 * - 横向多列网格（如总览资源）：先行后列、左侧先于右侧；
 * - 纵向列表（如配置组）：自上而下；
 * 呈现如同水波从左上角向右下角推开的错峰流动视觉效果。
 */
export function calculateCardDiagonalScore(
  rect: { left: number; top: number },
  rootRect: { left: number; top: number }
): number {
  const x = Math.max(0, rect.left - rootRect.left)
  const y = Math.max(0, rect.top - rootRect.top)
  return y + x * 0.65
}

/**
 * 依据卡片在屏幕视口中的 2D 物理坐标，将卡片按「从左上角到右下角」进行对角线投影排序。
 */
export function sortCardsFromTopLeft(cards: HTMLElement[], root: HTMLElement): HTMLElement[] {
  if (cards.length <= 1) return cards
  const rootRect = root.getBoundingClientRect()

  const scored = cards.map(card => {
    const rect = card.getBoundingClientRect()
    const score = calculateCardDiagonalScore(rect, rootRect)
    return { card, score }
  })

  scored.sort((a, b) => a.score - b.score)
  return scored.map(item => item.card)
}

/**
 * 计算非线性的错峰延迟：
 * 采用自然衰减的 Ease-Out 幂律曲线，使第一批卡片具有清晰的律动波浪感，
 * 后续卡片柔和收敛，彻底消除机械等距的线性呆滞感。
 */
export function calculateNonLinearDelay(index: number, total: number, speed = 1): number {
  if (total <= 1 || index <= 0) return 0
  if (total <= 3) {
    return Math.round(index * 34 * speed)
  }
  const totalWindow = 170 * speed
  const ratio = index / (total - 1)
  const curved = 1 - Math.pow(1 - ratio, 1.35)
  return Math.round(curved * totalWindow)
}

/**
 * 给排好序的卡片应用错峰上浮动画。
 * 动画结束后自动清理 class 与内联样式，保证 DOM 恢复纯净，不影响后续 hover、按压或拖拽交互。
 */
export function applyCardStaggerMotion(cards: HTMLElement[], sessionId: number) {
  if (motionReducedActive() || cards.length === 0) return

  const speed = motionSpeedValue()
  const total = cards.length

  cards.forEach((card, index) => {
    ;(card as unknown as Record<string, number>)[MOTION_SESSION_KEY] = sessionId
    const delay = calculateNonLinearDelay(index, total, speed)

    // 移除可能存在的旧动画类，触发回流后重新注入
    card.classList.remove('motion-card-stagger')
    card.style.setProperty('--card-stagger-delay', `${delay}ms`)
    void card.offsetWidth
    card.classList.add('motion-card-stagger')

    const handleEnd = (event: AnimationEvent) => {
      if (event.target !== card) return
      card.removeEventListener('animationend', handleEnd)
      card.classList.remove('motion-card-stagger')
      card.style.removeProperty('--card-stagger-delay')
    }
    card.addEventListener('animationend', handleEnd, { once: true })
  })
}

/**
 * 扫描当前根容器中的新卡片并执行错峰上浮动画。
 * 只针对当前会话中尚未播放过动画的新卡片生效。
 */
function scanAndAnimateCards(root: HTMLElement, sessionId: number) {
  const cards = findTopLevelCards(root)
  const unplayedCards = cards.filter(card => {
    return (card as unknown as Record<string, number>)[MOTION_SESSION_KEY] !== sessionId
  })

  if (unplayedCards.length === 0) return
  const sorted = sortCardsFromTopLeft(unplayedCards, root)
  applyCardStaggerMotion(sorted, sessionId)
}

/**
 * 路由切换时调用：开启新一轮卡片动效会话。
 * 支持异步数据加载（如 Overview / Statistics 异步拉取数据后挂载卡片）：
 * 在短时间内通过 MutationObserver 捕获后续插入的卡片。
 */
export function triggerCardStaggerMotion(root: HTMLElement | null) {
  if (typeof window === 'undefined' || typeof document === 'undefined') return
  if (!root || motionReducedActive()) return

  currentSessionId += 1
  const sessionId = currentSessionId

  if (activeObserver) {
    activeObserver.disconnect()
    activeObserver = null
  }
  if (sessionTimeoutId !== null) {
    window.clearTimeout(sessionTimeoutId)
    sessionTimeoutId = null
  }

  // 首帧立即扫描已有卡片
  requestAnimationFrame(() => {
    scanAndAnimateCards(root, sessionId)
  })

  // 监听异步渲染出来的新卡片
  let frameId: number | null = null
  activeObserver = new MutationObserver(() => {
    if (frameId !== null) cancelAnimationFrame(frameId)
    frameId = requestAnimationFrame(() => {
      scanAndAnimateCards(root, sessionId)
    })
  })

  activeObserver.observe(root, { childList: true, subtree: true })

  // 1.5 秒后断开监听，避免普通交互（表单打字、展开折叠）引发多余开销
  sessionTimeoutId = window.setTimeout(() => {
    if (activeObserver) {
      activeObserver.disconnect()
      activeObserver = null
    }
    sessionTimeoutId = null
  }, 1500)
}

/**
 * 供开发者工具「重播页面转场」调用：重新播放当前页面卡片从左上角逐个上浮的效果。
 */
export function replayCardStaggerMotion() {
  if (typeof document === 'undefined') return
  const root = document.getElementById('main-content')
  if (!root || motionReducedActive()) return

  currentSessionId += 1
  const sessionId = currentSessionId

  const cards = findTopLevelCards(root)
  const sorted = sortCardsFromTopLeft(cards, root)
  applyCardStaggerMotion(sorted, sessionId)
}
