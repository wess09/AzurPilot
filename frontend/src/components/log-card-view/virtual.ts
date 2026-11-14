/**
 * 从 LogCardView.tsx 原 1894-2015 行提取，纯搬迁未改动。
 * 日志卡片虚拟窗口的常量、高度预估与可见区间计算。
 */

import type { CardItem } from './aggregate'

// 虚拟化窗口与卡片高度预估

/** 卡片数达到该阈值才启用虚拟化窗口；更少时全量渲染开销更低。 */
export const VIRTUAL_THRESHOLD = 40
/** 虚拟窗口上下各多渲染的像素余量，减少快速滚动时的白屏。 */
export const OVERSCAN_BUFFER_PX = 800
const CARD_GAP_PX = 8

/** 滚动不足半段预渲染余量时复用当前窗口，减少视口边缘的挂载与卸载。 */
export function logWindowTop(scrollTop: number) {
  const step = OVERSCAN_BUFFER_PX / 2
  return Math.floor(scrollTop / step) * step
}

/** requestAnimationFrame 的环境兜底：无 window（测试/SSR）时退化为 16ms 的 setTimeout。 */
export const safeRaf = (cb: FrameRequestCallback): number => {
  if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
    return window.requestAnimationFrame(cb)
  }
  return setTimeout(cb, 16) as unknown as number
}

/** 与 safeRaf 配对取消；id 为 null 时忽略。 */
export const safeCancelRaf = (id: number | null) => {
  if (id === null) return
  if (typeof window !== 'undefined' && typeof window.cancelAnimationFrame === 'function') {
    window.cancelAnimationFrame(id)
  } else {
    clearTimeout(id)
  }
}

/**
 * 依据卡片类型与内部数据结构预估卡片渲染高度（包含 CSS padding/border 等）。
 */
export function getCardEstimatedHeight(card: CardItem): number {
  switch (card.type) {
    case 'single':
      return 34
    case 'stage_header':
      return 44
    case 'system_banner':
      return 74
    case 'perspective':
      return 172
    case 'map_grid':
      return Math.max(120, 52 + card.rows.length * 28 + 48)
    case 'cost_grid':
      return Math.max(120, 52 + card.rows.length * 28 + 48)
    case 'matrix_grid':
      return Math.max(100, 52 + card.rows.length * 24 + 48)
    case 'property_sheet':
      return Math.max(70, 48 + card.items.length * 26)
    case 'data_table':
      return Math.max(90, 48 + card.rows.length * 28 + 36)
    case 'error_context':
      return 280
    case 'traceback':
      return 220
    case 'llm_report':
      return 260
    default:
      return 34
  }
}

/**
 * 二分查找当前视口区域 [visibleTop, visibleBottom] 所覆盖的卡片索引范围 [startIndex, endIndex]。
 */
export function findVisibleRange(
  offsets: number[],
  heights: number[],
  visibleTop: number,
  visibleBottom: number,
  totalCount: number
): [number, number] {
  if (totalCount === 0) return [0, 0]

  // 若视口顶部已经超出全部卡片总底部，直接锁定末尾卡片。
  const lastBottom = (offsets[totalCount - 1] ?? 0) + (heights[totalCount - 1] ?? 0)
  if (visibleTop >= lastBottom) {
    return [totalCount - 1, totalCount - 1]
  }

  // 若视口底部小于等于 0，直接锁定第一张卡片。
  if (visibleBottom <= 0) {
    return [0, 0]
  }

  // 二分查找满足 offsets[i] + heights[i] >= visibleTop 的最小 i（startIndex）。
  let low = 0
  let high = totalCount - 1
  let startIndex = 0

  while (low <= high) {
    const mid = (low + high) >> 1
    const itemBottom = offsets[mid] + heights[mid]
    if (itemBottom >= visibleTop) {
      startIndex = mid
      high = mid - 1
    } else {
      low = mid + 1
    }
  }

  // 二分查找满足 offsets[i] <= visibleBottom 的最大 i（endIndex）。
  low = startIndex
  high = totalCount - 1
  let endIndex = startIndex

  while (low <= high) {
    const mid = (low + high) >> 1
    if (offsets[mid] <= visibleBottom) {
      endIndex = mid
      low = mid + 1
    } else {
      high = mid - 1
    }
  }

  return [Math.max(0, startIndex), Math.min(totalCount - 1, Math.max(startIndex, endIndex))]
}

export { CARD_GAP_PX }
