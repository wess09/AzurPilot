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
  // 左列调度器是一整块玻璃面板，必须作为一个动效单元整体入场：
  // 分开动的话，面板里那块 .panel（「统计」行）会自己缩放淡入，玻璃背板按新比例重采样，
  // 模糊就会在动画期间跳一下；而面板本体原地不动，又跟不上页面。
  '.instance-page-rail-wrap',
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
function findTopLevelCards(root: HTMLElement): HTMLElement[] {
  const allCards = Array.from(root.querySelectorAll<HTMLElement>(CARD_SELECTORS))
  return allCards.filter(card => {
    // 隐藏元素的 rect 全为 0：没有可播的入场动画，参与对角排序还会全部堆到 (0, 0)。
    if (card.offsetWidth === 0 && card.offsetHeight === 0 && card.getClientRects().length === 0) {
      return false
    }
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

  // 已经播放中的卡片需要先取消旧动画；首播无需同步量布局。
  const playing = cards.filter(card => card.classList.contains('motion-card-stagger'))
  for (const card of playing) card.classList.remove('motion-card-stagger')
  if (playing.length) void playing[0].offsetWidth

  cards.forEach((card, index) => {
    // 双重断言绕开 HTMLElement 的类型限制：键名带 __azurpilot 前缀，不会撞上真实属性。
    ;(card as unknown as Record<string, number>)[MOTION_SESSION_KEY] = sessionId

    const delay = calculateNonLinearDelay(index, total, speed)
    card.style.setProperty('--card-stagger-delay', `${delay}ms`)
    card.classList.add('motion-card-stagger')

    const handleEnd = (event: AnimationEvent) => {
      if (event.target !== card) return
      card.removeEventListener('animationend', handleEnd)
      card.classList.remove('motion-card-stagger')
      card.style.removeProperty('--card-stagger-delay')
    }
    card.addEventListener('animationend', handleEnd)
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

function includesTaskSettings(node: Node) {
  return node instanceof Element && (node.matches('.task-config-settings-inner') || node.querySelector('.task-config-settings-inner') !== null)
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

  let frameId: number | null = null
  const scan = () => {
    if (frameId !== null) cancelAnimationFrame(frameId)
    frameId = null
    if (sessionId === currentSessionId) scanAndAnimateCards(root, sessionId)
  }
  const scheduleScan = () => {
    if (frameId === null) frameId = requestAnimationFrame(scan)
  }

  // 任务设置挂载时在首次绘制前定位卡片，避免卡片先在终点显示一帧再跳到起点。
  // 其他异步更新继续合并到每帧一次，避免日志等高频变更反复扫描。
  activeObserver = new MutationObserver(records => {
    if (records.some(record => Array.from(record.addedNodes).some(includesTaskSettings))) scan()
    else scheduleScan()
  })

  activeObserver.observe(root, { childList: true, subtree: true })
  if (includesTaskSettings(root)) scan()
  else scheduleScan()

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
