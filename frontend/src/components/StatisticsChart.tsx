/**
 * @fileoverview 统计图表（折线图、柱状图、堆叠图）渲染组件。
 *
 * 内部实现已按内聚单元拆分至 statistics-chart/（纯搬迁）：
 * shared / chart-colors / chart-icons / use-chart-selection / use-chart-render /
 * chart-controls / chart-picker / chart-metrics。
 */

import { createPortal } from 'react-dom'
import { useEffect, useLayoutEffect, useMemo, useRef, type ReactNode } from 'react'
import * as echarts from 'echarts/core'
import { LineChart, CandlestickChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent, ToolboxComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type {StatSeries} from '../api/types'
import { Empty } from './ui'
import { Button } from './ui/button'
import {buildSeriesView} from './statisticsData'
import { updateStatisticsPrefs } from '../app/statisticsPrefs'
import { useApp } from '../app/context'
import { getSeriesColor } from './statistics-chart/chart-colors'
import { useChartSelection } from './statistics-chart/use-chart-selection'
import { useChartRender } from './statistics-chart/use-chart-render'
import { buildChartControls } from './statistics-chart/chart-controls'
import { buildChartPicker } from './statistics-chart/chart-picker'
import { buildChartMetrics } from './statistics-chart/chart-metrics'

export { bucketOptions } from './statistics-chart/shared'

/*
 * 样式索引（混合分层 L2：样式横跨多域文件，无法 colocate）。
 * - styles/insights.css      统计域主文件：statistics-controls / statistics-metrics-* / stat-chip-* / stat-metric-* / stat-card-actions / statistics-chart-plot / chart-canvas / panel-note
 * - styles/forms.css         表单域：.statistics-controls select/input 控件高度（--form-height）
 * - styles/a11y-modern.css   无障碍段：隐藏窄面板的 .instance-panel-stats .statistics-controls.period-controls
 * - styles/resource-card.css preview-error（时间范围校验错误提示）
 */

echarts.use([LineChart, CandlestickChart, GridComponent, TooltipComponent, DataZoomComponent, ToolboxComponent, LegendComponent, CanvasRenderer])

/** 图表主体。 */
export function StatisticsChart({series, expanded = false, onToggleExpanded, title, category = 'resources', foldControl, plotFoldControl, compact = false, compactControl, showPicker = true, pickerControl, pickerMuted = false, stackedRise = false, stackedControl, zeroBase = false, zeroBaseControl, filtered = [], onToggleFilter}: {
  series: StatSeries[]
  foldControl?: ReactNode
  plotFoldControl?: ReactNode
  /** 表头是否用紧凑排列：一行一个资源。 */
  compact?: boolean
  /** 表头容器内的排列方式开关。 */
  compactControl?: ReactNode
  /** 是否展示表头选取器：非编辑模式下可以隐藏，只留已选中的卡片。 */
  showPicker?: boolean
  /** 表头容器内的选取器显隐开关。 */
  pickerControl?: ReactNode
  /** 已设为隐藏选取器的页面：编辑模式里把这一行淡色预览。 */
  pickerMuted?: boolean
  /** 行动力曲线是否按涨跌染色（叠涨视图）。 */
  stackedRise?: boolean
  /** 表头容器内的叠涨开关。 */
  stackedControl?: ReactNode
  /** 纵轴起点是否固定为 0：关闭时轴跟随可见数据范围。 */
  zeroBase?: boolean
  /** 表头容器内的纵轴起点开关。 */
  zeroBaseControl?: ReactNode
  /** 被点掉曲线的资源键：表头保留并淡色，不画进图里。 */
  filtered?: string[]
  /** 点表头卡片切换该资源的曲线显示。 */
  onToggleFilter?: (key: string) => void
  expanded?: boolean
  onToggleExpanded: () => void
  // 放大视图用分区名字当标题：此时整页工具栏（含分区切换）已被面板盖住。
  title?: string
  category?: string
}) {
  const {ui, language, theme} = useApp()
  const {selectedKeys, setSelectedKeys, mode, setMode, axisMode, setAxisMode, bucket, setBucket, from, setFrom, to, setTo} = useChartSelection({category, series})

  useEffect(() => {
    if (!expanded) return
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') onToggleExpanded() }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [expanded, onToggleExpanded])

  const element = useRef<HTMLDivElement>(null)

  // 全屏放大模式下根据固定视口计算高度；常规贯穿模式下沿用样式表定义的舒适高度。
  useLayoutEffect(() => {
    const canvas = element.current
    const panel = canvas?.closest<HTMLElement>('.statistics-chart')
    if (!canvas || !panel) return
    if (!expanded) {
      canvas.style.height = ''
      return
    }
    const resize = () => {
      const panelBox = panel.getBoundingClientRect()
      const canvasBox = canvas.getBoundingClientRect()
      // 画布上方的高度按坐标量：画布是面板的孙节点，不是直接子节点。
      const above = canvasBox.top - panelBox.top + panel.scrollTop
      const next = Math.max(240, Math.round(panel.clientHeight - above))
      if (Math.abs(next - canvasBox.height) < 1) return
      canvas.style.height = `${next}px`
    }
    resize()
    // 面板高度、上方内容高度（换语言会让芯片换行）变化时都要重算。
    const observer = new ResizeObserver(resize)
    observer.observe(panel)
    for (const child of panel.children) if (child !== canvas) observer.observe(child)
    return () => observer.disconnect()
  }, [series, language, expanded])

  function toggleKey(key: string) {
    setSelectedKeys(prev => (prev.includes(key) ? (prev.length <= 1 ? prev : prev.filter(k => k !== key)) : [...prev, key]))
  }

  function selectOnly(key: string) {
    setSelectedKeys([key])
  }

  function setAsPrimary(key: string) {
    setSelectedKeys(prev => [key, ...prev.filter(k => k !== key)])
  }

  const view = useMemo(() => buildSeriesView(series, {selectedKeys, mode, bucket, from, to}), [series, selectedKeys, mode, bucket, from, to])
  const {isSingle, effectiveBucket} = view
  // 时间范围写回偏好：原始记录卡与图表读同一份筛选。
  useEffect(() => {
    updateStatisticsPrefs({rangeFrom: from, rangeTo: to})
  }, [from, to])

  const isCandlestick = mode === 'candlestick'
  const seriesData = useMemo(() => view.seriesData.map((item, index) => ({...item, color: getSeriesColor(item.series.key, index), index})), [view])

  const categoryTimes = useMemo(() => {
    if (!isCandlestick) return []
    const set = new Set<string>()
    for (const item of seriesData) for (const b of item.buckets) set.add(b.time)
    return [...set].sort()
  }, [isCandlestick, seriesData])

  // 被点掉曲线的资源仍留在表头（淡色），只是不再画进图里。
  const shownData = useMemo(() => seriesData.filter(item => !filtered.includes(item.series.key)), [seriesData, filtered])

  const hasPoints = shownData.some(item => item.points.length > 0)
  useEffect(() => {
    const el = element.current
    return () => {
      if (el) echarts.getInstanceByDom(el)?.dispose()
    }
  }, [])

  const single = seriesData[0]

  useChartRender({element, seriesData, shownData, hasPoints, isCandlestick, axisMode, isSingle, categoryTimes, category, language, ui, theme, stackedRise, zeroBase})

  // 图表设置（类型、坐标轴、采样粒度、时间范围）排在图表下方：先看数据，再决定怎么画。
  const {controls, rangeError} = buildChartControls({ui, mode, setMode, bucket, setBucket, axisMode, setAxisMode, effectiveBucket, isCandlestick, isSingle, from, setFrom, to, setTo})

  // 组合页里两张图卡标题相同、分不出是哪一张，带短名前缀后可以区分。
  const headingLabel = category === 'resources' ? ui('stats.chartHeading.resources') : category === 'action' ? ui('stats.chartHeading.action') : ui('stats.trendDetails')

  const picker = buildChartPicker({series, selectedKeys, toggleKey, selectOnly, setAsPrimary, isCandlestick, isSingle, ui, compactControl, stackedControl, pickerControl, zeroBaseControl, pickerMuted, showPicker})
  const metrics = buildChartMetrics({isSingle, single, seriesData, compact, filtered, selectedKeys, shownData, onToggleFilter, isCandlestick, ui})

  const chart = (
    <section className={`panel statistics-chart ${expanded ? 'chart-expanded' : ''}`}>
      <div className="panel-heading">
        <h2>{expanded && title ? title : headingLabel}</h2>
        <div className="stat-card-actions">{foldControl}<Button variant="ghost" size="sm" onClick={onToggleExpanded}>{expanded ? ui('stats.collapseChart') : ui('stats.expandChart')}</Button></div>
      </div>

      {picker}

      {hasPoints ? (
        <>
          {metrics}

          <div className="statistics-chart-plot">{plotFoldControl}<div ref={element} className="chart-canvas" role="img" aria-label={ui('stats.chartAria', {label: shownData.map(item => item.series.label).join(', ')})}/></div>
          {controls}
          {rangeError}
          <p className="panel-note">{ui('stats.chartHint')}</p>
        </>
      ) : (
        <>
          {controls}
          {rangeError}
          <Empty title={ui('stats.noValidTitle')}>{ui('stats.noValidHint')}</Empty>
        </>
      )}
    </section>
  )

  // 放大态挂到 body：卡片链给每张卡设了 z-index，面板留在卡内会被顶栏盖住。
  return expanded ? createPortal(chart, document.body) : chart
}
