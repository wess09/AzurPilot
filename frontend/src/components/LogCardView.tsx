/**
 * @fileoverview 结构化运行日志卡片流渲染与虚拟滚动视图组件。
 */

import {
  memo,
  useEffect,
  useLayoutEffect,
  useRef,
  useCallback,
  useState,
  useMemo,
  type ReactNode,
  type RefObject,
} from 'react'
import type { LogEntry } from '../api/types'
import {
  aggregateEntriesToCards,
  type CardItem,
} from './log-card-view/aggregate'
import {
  CostGridCard,
  DataTableCard,
  LlmReportCard,
  MatrixGridCard,
  PerspectiveCard,
  PropertySheetCard,
  SingleLogLineCard,
  StageHeaderCard,
  SystemBannerCard,
} from './log-card-view/cards'
import { MapGridCard } from './log-card-view/map-grid'
import { ErrorContextCard, TracebackCard } from './log-card-view/traceback'
import {
  CARD_GAP_PX,
  OVERSCAN_BUFFER_PX,
  VIRTUAL_THRESHOLD,
  findVisibleRange,
  getCardEstimatedHeight,
  logWindowTop,
  safeCancelRaf,
  safeRaf,
} from './log-card-view/virtual'

/*
 * 样式索引（混合分层 L2：本文件挂 130+ 全局类，横跨多域文件，无法 colocate）。
 * - styles/log.css              日志卡片域：log-card / log-line / log-lvl / log-ts / hl-* / badge-pill / log-divider 等
 *                               （hl-* 与 log-ts 在 log.css 与 theme-primitives.css:138-144 双定义：log.css 8 处 hl-* + log-ts，后者 6 处 hl-* + log-ts，主题变量覆写依赖文件顺序，故留 L2）
 * - styles/map-grid.css         地图格子域：cell-* / dot-sea / legend-* / map-ascii-table
 * - styles/map-cost.css         代价表域：cost-table / cost-cell / matrix-row / dot-origin / dot-cost-*
 * - styles/error-card.css       错误卡与回溯域：error-card 复合在 log-card 上（.error-card 自身无规则），子元素规则 error-header / error-body / error-section / frame-* / locals-* / llm-* / data-table-viewport / grid-depth-line 等都在此文件
 * - styles/feedback.css         反馈域：log-card-line / banner-double-rule / banner-title-text
 * - styles/theme-primitives.css 日志高亮主题段（:138-144）：lvl-* / log-ts / hl-* / log-search-match 绑定 --theme-log-* 变量
 */

/**
 * 单个卡片类型分发渲染。
 */
function renderCardItem(card: CardItem, search: string): ReactNode {
  switch (card.type) {
    case 'map_grid':
      return <MapGridCard key={card.id} card={card} />
    case 'perspective':
      return <PerspectiveCard key={card.id} card={card} />
    case 'cost_grid':
      return <CostGridCard key={card.id} card={card} />
    case 'matrix_grid':
      return <MatrixGridCard key={card.id} card={card} />
    case 'property_sheet':
      return <PropertySheetCard key={card.id} card={card} search={search} />
    case 'data_table':
      return <DataTableCard key={card.id} card={card} />
    case 'error_context':
      return <ErrorContextCard key={card.id} card={card} />
    case 'traceback':
      return <TracebackCard key={card.id} card={card} />
    case 'llm_report':
      return <LlmReportCard key={card.id} card={card} />
    case 'system_banner':
      return <SystemBannerCard key={card.id} card={card} />
    case 'stage_header':
      return <StageHeaderCard key={card.id} card={card} />
    case 'single':
    default:
      return <SingleLogLineCard key={card.id} card={card} search={search} />
  }
}

interface LogCardViewProps {
  entries: LogEntry[]
  search: string
  scrollRef?: RefObject<HTMLDivElement | null>
}

/**
 * 日志卡片流主组件：先把日志聚合成卡片，少于阈值全量渲染，达到阈值走虚拟窗口
 * （估算高度占位，ResizeObserver 实测修正，滚动位置二分定位可见区间）。
 *
 * @param search 搜索词，命中片段以 <mark> 高亮。
 * @param scrollRef 外层滚动容器引用；不传时回退到组件的最近父元素。
 */
export const LogCardView = memo(function LogCardView({
  entries,
  search,
  scrollRef,
}: LogCardViewProps) {
  const cards = useMemo(() => aggregateEntriesToCards(entries), [entries])
  const containerRef = useRef<HTMLDivElement>(null)
  const isVirtual = cards.length >= VIRTUAL_THRESHOLD

  // 动态测量的高度缓存（按 card.id 记录实际渲染高度）。
  const heightCacheRef = useRef<Map<number, number>>(new Map())
  const [measureVersion, setMeasureVersion] = useState(0)
  const measureRafRef = useRef<number | null>(null)

  // 高度变化合并到一帧再重渲染：ResizeObserver 高频触发，逐次 setState 会拖垮滚动。
  const requestMeasureUpdate = useCallback(() => {
    if (measureRafRef.current !== null) return
    measureRafRef.current = safeRaf(() => {
      measureRafRef.current = null
      setMeasureVersion(v => v + 1)
    })
  }, [])

  const [scrollState, setScrollState] = useState({ scrollTop: 0, clientHeight: 800 })

  // 获取外层滚动容器（优先传入的 scrollRef，其次找最近父级）。
  const getScrollElement = useCallback(() => {
    return scrollRef?.current ?? containerRef.current?.parentElement ?? null
  }, [scrollRef])

  // 监听外部滚动容器的滚动与尺寸变化。
  useEffect(() => {
    if (!isVirtual) return
    const scrollEl = getScrollElement()
    if (!scrollEl) return

    const syncWindow = () => {
      const scrollTop = logWindowTop(scrollEl.scrollTop)
      const clientHeight = scrollEl.clientHeight || 800
      setScrollState(previous => previous.scrollTop === scrollTop && previous.clientHeight === clientHeight
        ? previous : {scrollTop, clientHeight})
    }
    syncWindow()

    let scrollRafId: number | null = null
    const onScroll = () => {
      if (scrollRafId !== null) return
      scrollRafId = safeRaf(() => {
        scrollRafId = null
        syncWindow()
      })
    }

    scrollEl.addEventListener('scroll', onScroll, { passive: true })

    let resizeObserver: ResizeObserver | null = null
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(syncWindow)
      resizeObserver.observe(scrollEl)
    }

    return () => {
      scrollEl.removeEventListener('scroll', onScroll)
      if (scrollRafId !== null) safeCancelRaf(scrollRafId)
      resizeObserver?.disconnect()
    }
  }, [getScrollElement, isVirtual])

  // ResizeObserver 观察可见卡片的实际高度变动（折叠/展开/动态排版都会改变占位）。
  const cardObserverRef = useRef<ResizeObserver | null>(null)
  const cardNodes = useRef(new Set<HTMLDivElement>())
  useLayoutEffect(() => {
    if (!isVirtual || typeof ResizeObserver === 'undefined') return

    const observer = new ResizeObserver((observerEntries) => {
      let changed = false
      for (const entry of observerEntries) {
        const el = entry.target as HTMLElement
        const idAttr = el.getAttribute('data-card-id')
        if (!idAttr) continue
        const cardId = parseInt(idAttr, 10)
        const measured = entry.borderBoxSize?.[0]?.blockSize ?? entry.contentRect.height
        if (measured > 0) {
          // 变化不足 2px 当作测量抖动忽略，避免亚像素差异反复触发重排。
          const prev = heightCacheRef.current.get(cardId)
          if (prev === undefined || Math.abs(prev - measured) >= 2) {
            heightCacheRef.current.set(cardId, measured)
            changed = true
          }
        }
      }
      if (changed) {
        requestMeasureUpdate()
      }
    })
    cardObserverRef.current = observer
    for (const node of cardNodes.current) observer.observe(node)

    return () => {
      observer.disconnect()
      cardObserverRef.current = null
      if (measureRafRef.current !== null) {
        safeCancelRaf(measureRafRef.current)
        measureRafRef.current = null
      }
    }
  }, [isVirtual, requestMeasureUpdate])

  const registerCardRef = useCallback((node: HTMLDivElement | null) => {
    if (!node) return
    const nodes = cardNodes.current
    nodes.add(node)
    cardObserverRef.current?.observe(node)
    return () => {
      nodes.delete(node)
      cardObserverRef.current?.unobserve(node)
    }
  }, [])

  // 测量结果最多保留当前一屏历史窗口的数量级，连续运行也不会累积旧日志行高。
  useEffect(() => {
    const measured = heightCacheRef.current
    if (measured.size <= 2 * cards.length) return
    const retained = new Set(cards.map(card => card.id))
    for (const id of measured.keys()) {
      if (!retained.has(id)) measured.delete(id)
    }
  }, [cards])

  // 滚动只移动窗口，偏移表仅在卡片或实测高度变化后重算。
  const {heights, offsets, totalHeight} = useMemo(() => {
    const heights: number[] = []
    const offsets: number[] = []
    let height = 0
    if (isVirtual) {
      for (const card of cards) {
        const rowHeight = (heightCacheRef.current.get(card.id) ?? getCardEstimatedHeight(card)) + CARD_GAP_PX
        heights.push(rowHeight)
        offsets.push(height)
        height += rowHeight
      }
    }
    return {heights, offsets, totalHeight: Math.max(0, height - CARD_GAP_PX)}
  }, [cards, isVirtual, measureVersion])

  // 卡片不多时直接全量渲染，省去窗口计算与测量开销。
  if (!isVirtual) {
    return (
      <div ref={containerRef} className="log-cards-container">
        {cards.map((card) => renderCardItem(card, search))}
      </div>
    )
  }

  const totalCount = cards.length

  const visibleTop = Math.max(0, scrollState.scrollTop - OVERSCAN_BUFFER_PX)
  const visibleBottom = scrollState.scrollTop + scrollState.clientHeight + OVERSCAN_BUFFER_PX

  const [startIndex, endIndex] = findVisibleRange(offsets, heights, visibleTop, visibleBottom, totalCount)
  const paddingTop = offsets[startIndex] ?? 0
  const bottomItemEnd = Math.max(0, (offsets[endIndex] ?? 0) + (heights[endIndex] ?? 0) - CARD_GAP_PX)
  const paddingBottom = Math.max(0, totalHeight - bottomItemEnd)

  const visibleCards = cards.slice(startIndex, endIndex + 1)

  return (
    <div
      ref={containerRef}
      className="log-cards-container"
      style={{
        paddingTop: `${paddingTop}px`,
        paddingBottom: `${paddingBottom}px`,
        boxSizing: 'border-box',
      }}
    >
      {visibleCards.map((card) => (
        <div key={card.id} data-card-id={card.id} ref={registerCardRef} className="log-card-virtual-item">
          {renderCardItem(card, search)}
        </div>
      ))}
    </div>
  )
})

export {
  TOKEN_CACHE_MAX,
  clearTokenCache,
  getTokenCacheSize,
  renderTokens,
} from './log-card-view/tokens'
export {
  aggregateEntriesToCards,
  clearAggregationCache,
  getAggregationCacheInfo,
} from './log-card-view/aggregate'
export {
  renderCellContent,
  MapGridCard,
} from './log-card-view/map-grid'
export {
  PerspectiveCard,
  PropertySheetCard,
  DataTableCard,
  LlmReportCard,
  MatrixGridCard,
  getCostHeatmapStyle,
  CostGridCard,
  SystemBannerCard,
  StageHeaderCard,
  SingleLogLineCard,
} from './log-card-view/cards'
export {
  ErrorContextCard,
  TracebackCard,
} from './log-card-view/traceback'
export {
  VIRTUAL_THRESHOLD,
  OVERSCAN_BUFFER_PX,
  logWindowTop,
  safeRaf,
  safeCancelRaf,
  getCardEstimatedHeight,
  findVisibleRange,
} from './log-card-view/virtual'
