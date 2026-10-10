/**
 * @fileoverview 统计图表（折线图、柱状图、堆叠图）渲染组件。
 */

import type {ReactNode, KeyboardEvent as ReactKeyboardEvent} from 'react'
import { createPortal } from 'react-dom'
import { Select } from './FormControls'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { LineChart, CandlestickChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent, ToolboxComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type {StatSeries} from '../api/types'
import { Empty } from './ui'
import {resolveIcon} from './StatisticsTable'
import {buildSeriesView, isActionPointSeries, riseFallSegments} from './statisticsData'
import { useApp } from '../app/context'
import { usesMaterial } from '../app/theme'
import {
  readStatisticsPrefs,
  updateStatisticsPrefs,
  setSelectedKeysForCategory,
  getSelectedKeysForCategory,
  type ChartMode,
  type ChartAxisMode,
} from '../app/statisticsPrefs'

echarts.use([LineChart, CandlestickChart, GridComponent, TooltipComponent, DataZoomComponent, ToolboxComponent, LegendComponent, CanvasRenderer])

const RESOURCE_PALETTE: Record<string, string> = {
  oil: '#10b981', coin: '#f59e0b', cube: '#0ea5e9', gem: '#f43f5e', pt: '#8b5cf6',
  core: '#06b6d4', medal: '#e11d48', merit: '#d97706', guild_coin: '#64748b',
  ap: '#3b82f6', asset: '#84cc16', distance: '#2563eb', yellow_coins: '#eab308', purple_coins: '#a855f7',
}
const DEFAULT_PALETTE = ['#159b88', '#f59e0b', '#0ea5e9', '#ec4899', '#8b5cf6', '#10b981', '#f97316', '#6366f1', '#14b8a6']

function getSeriesColor(key: string, index: number, fallback?: string): string {
  return RESOURCE_PALETTE[key] ?? (index === 0 && fallback ? fallback : DEFAULT_PALETTE[index % DEFAULT_PALETTE.length])
}

const iconBase = import.meta.env.BASE_URL
const chartResourceIcons: Record<string, string> = {
  '石油': `${iconBase}oil.webp`,
  '物资': `${iconBase}gold.webp`,
  '钻石': `${iconBase}diamond.webp`,
  '心智魔方': `${iconBase}cube.webp`,
  '魔方': `${iconBase}cube.webp`,
  '活动 PT': `${iconBase}pt.webp`,
  '核心数据': `${iconBase}core_data.webp`,
  '荣誉勋章': `${iconBase}honor_medal.webp`,
  '功勋': `${iconBase}merit.webp`,
  '舰队币': `${iconBase}stamina.webp`,
  '心智单元': `${iconBase}cognitive_chips.webp`,
  '行动力': `${iconBase}guild_coin.webp`,
  '行动力资产': `${iconBase}action_asset.webp`,
  '海里数': `${iconBase}nautical_miles.webp`,
  '作战补给凭证': `${iconBase}supply_token.webp`,
  '特别兑换凭证': `${iconBase}special_token.webp`,
  '完成委托': `${iconBase}honor_medal.webp`,
}

function getChartIcon(series: StatSeries): string | undefined {
  if (series.icon) return resolveIcon(series.icon)?.src
  const {label} = series
  if (chartResourceIcons[label]) return chartResourceIcons[label]
  for (const [key, icon] of Object.entries(chartResourceIcons)) {
    if (label.includes(key) || key.includes(label)) return icon
  }
  return undefined
}

/** 图表主体。紧凑主题把标题行与「放大查看」上提到页面工具栏（`heading=false`），
    并把报表附带的表格并进同一面板，避免同一页出现两个顶层区域。 */
export function StatisticsChart({series, heading = true, expanded = false, onToggleExpanded, title, initialMode, category = 'resources', foldControl, plotFoldControl, compact = false, compactControl, showPicker = true, pickerControl, pickerMuted = false, stackedRise = false, stackedControl, zeroBase = false, zeroBaseControl, filtered = [], onToggleFilter}: {
  series: StatSeries[]
  heading?: boolean
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
  /* 放大视图用分区名字当标题：此时整页工具栏（含分区切换）已被面板盖住。 */
  title?: string
  initialMode?: ChartMode
  category?: string
}) {
  const {ui, language, theme} = useApp()
  const [selectedKeys, setSelectedKeysState] = useState<string[]>(() => {
    const remembered = getSelectedKeysForCategory(category, series)
    if (remembered.length > 0) return remembered
    const active = series.find(item => item.points.length)?.key ?? series[0]?.key
    return active ? [active] : []
  })

  const setSelectedKeys = useCallback((updater: string[] | ((prev: string[]) => string[])) => {
    setSelectedKeysState(prev => {
      const next = typeof updater === 'function' ? updater(prev) : updater
      setSelectedKeysForCategory(category, next)
      return next
    })
  }, [category])

  const [mode, setModeState] = useState<ChartMode>(() => initialMode ?? readStatisticsPrefs().chartMode)
  const setMode = useCallback((next: ChartMode) => {
    setModeState(next)
    updateStatisticsPrefs({chartMode: next})
  }, [])

  const [axisMode, setAxisModeState] = useState<ChartAxisMode>(() => readStatisticsPrefs().chartAxisMode)
  const setAxisMode = useCallback((next: 'separate' | 'unified') => {
    setAxisModeState(next)
    updateStatisticsPrefs({chartAxisMode: next})
  }, [])

  const [bucket, setBucketState] = useState(() => {
    const saved = readStatisticsPrefs().bucket
    const activeMode = initialMode ?? readStatisticsPrefs().chartMode
    return activeMode === 'candlestick' && saved === 0 ? 60 : saved
  })
  const setBucket = useCallback((next: number) => {
    setBucketState(next)
    updateStatisticsPrefs({bucket: next})
  }, [])

  const [from, setFrom] = useState(() => readStatisticsPrefs().rangeFrom)
  const [to, setTo] = useState(() => readStatisticsPrefs().rangeTo)

  useEffect(() => {
    if (!expanded) return
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') onToggleExpanded() }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [expanded, onToggleExpanded])

  const element = useRef<HTMLDivElement>(null)

  /* 全屏放大模式下根据固定视口计算高度；常规贯穿模式下沿用样式表定义的舒适高度。 */
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
      /* 画布上方的高度按坐标量：画布是面板的孙节点，不是直接子节点。 */
      const above = canvasBox.top - panelBox.top + panel.scrollTop
      const next = Math.max(240, Math.round(panel.clientHeight - above))
      if (Math.abs(next - canvasBox.height) < 1) return
      canvas.style.height = `${next}px`
    }
    resize()
    /* 面板高度、上方内容高度（换语言会让芯片换行）变化时都要重算。 */
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
  /* 时间范围写回偏好：原始记录卡与图表读同一份筛选。 */
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

  /* 被点掉曲线的资源仍留在表头（淡色），只是不再画进图里。 */
  const shownData = useMemo(() => seriesData.filter(item => !filtered.includes(item.series.key)), [seriesData, filtered])

  const hasPoints = shownData.some(item => item.points.length > 0)
  useEffect(() => {
    const el = element.current
    return () => {
      if (el) echarts.getInstanceByDom(el)?.dispose()
    }
  }, [])

  const single = seriesData[0]

  useEffect(() => {
    if (!element.current || !hasPoints) return
    const container = element.current
    const chart = echarts.getInstanceByDom(container) ?? echarts.init(container, undefined, {locale: language.startsWith('zh') ? 'ZH' : 'EN'})

    /* 重绘只取决于下面这几个 CSS 变量。这个观察者还会被与图表无关的 <html> style
       写入触发（例如指针光效的 --mx/--my），所以先比签名再决定要不要重建。 */
    let renderedSignature = ''
    function render() {
      const colors = getComputedStyle(document.documentElement)
      const text = colors.getPropertyValue('--text').trim() || '#82929f'
      const minimal = !usesMaterial(theme)
      const primary = colors.getPropertyValue('--theme-chart-primary').trim() || colors.getPropertyValue('--accent').trim()
      const secondary = colors.getPropertyValue('--theme-chart-secondary').trim() || colors.getPropertyValue('--secondary').trim()
      const rise = colors.getPropertyValue('--theme-chart-rise').trim() || '#dc2626'
      const fall = colors.getPropertyValue('--theme-chart-fall').trim() || '#16a34a'
      /* 网格线只铺在图表内部那张二级面上，透明度跟随它的不透明度。 */
      const gridOpacity = Math.min(1, Math.max(0, (parseFloat(colors.getPropertyValue('--theme-plate-alpha')) || 100) / 100))
      const surface = colors.getPropertyValue('--surface').trim()
      const border = colors.getPropertyValue('--border').trim()
      const accentSoft = colors.getPropertyValue('--accent-soft').trim()
      const signature = `${theme}|${text}|${primary}|${secondary}|${rise}|${fall}|${surface}|${border}|${accentSoft}|${gridOpacity}`
      if (signature === renderedSignature) return
      renderedSignature = signature
      const colorFor = (item: typeof seriesData[number]) => isSingle ? (minimal ? primary : item.color) : item.color
      /* 观感补全用的整图时间跨度。 */
      let axisStart = Number.POSITIVE_INFINITY
      let axisEnd = Number.NEGATIVE_INFINITY
      for (const item of shownData) {
        for (const bucket of item.buckets) {
          const ms = new Date(bucket.time.replace(' ', 'T')).getTime()
          if (!Number.isFinite(ms)) continue
          if (ms < axisStart) axisStart = ms
          if (ms > axisEnd) axisEnd = ms
        }
      }
      const padRange = Number.isFinite(axisStart) && axisEnd > axisStart
      /* 只补绘制用的点，不改数据、指标与记录。 */
      const padPairs = (pairs: Array<[number, number]>): Array<[number, number]> => {
        if (category === 'storage' || !padRange || pairs.length === 0) return pairs
        const padded: Array<[number, number]> = [...pairs]
        if (padded[0][0] > axisStart) padded.unshift([axisStart, 0])
        const last = padded[padded.length - 1]
        if (last[0] < axisEnd) padded.push([axisEnd, last[1]])
        return padded
      }
      /* 涨跌分段模式下只补下跌段。 */
      const padFall = (segments: Array<number[] | '-'>): Array<number[] | '-'> => {
        if (!padRange || segments.length === 0) return segments
        const pairs = segments.filter((entry): entry is number[] => entry !== '-')
        if (pairs.length === 0) return segments
        const padded: Array<number[] | '-'> = [...segments]
        if (pairs[0][0] > axisStart) padded.unshift([axisStart, 0])
        const last = pairs[pairs.length - 1]
        if (last[0] < axisEnd) padded.push([axisEnd, last[1]])
        return padded
      }

      let yAxes: any[] = []
      if (isSingle || axisMode === 'unified') {
        yAxes = [{type: 'value', scale: true, splitLine: {lineStyle: {color: border, opacity: gridOpacity}}, axisLabel: {color: text}}]
      } else {
        const c0 = colorFor(seriesData[0]), c1 = colorFor(seriesData[1])
        yAxes = [
          {type: 'value', scale: true, position: 'left', splitLine: {lineStyle: {color: border, opacity: gridOpacity}}, axisLine: {show: true, lineStyle: {color: c0}}, axisLabel: {color: c0}},
          {type: 'value', scale: true, position: 'right', splitLine: {show: false}, axisLine: {show: true, lineStyle: {color: c1}}, axisLabel: {color: c1}},
        ]
      }


      /* 纵轴固定：下界钉在 0，上界仍由 ECharts 按全量数据算，与「从 0 开始的自适应」同解。 */
      if (zeroBase) yAxes = yAxes.map(axis => ({...axis, min: 0}))

      /* 每条曲线落在哪个 Y 轴上：单页与统一轴都用左轴。 */
      /* 大小轴归属：左轴小值、右轴大值。 */
      const BIG_AXIS_KEYS = new Set(['asset', 'yellow_coins', 'distance'])
      const SMALL_AXIS_KEYS = new Set(['ap', 'purple_coins'])
      const BIG_AXIS_RATIO = 0.05
      const peakOf = (item: {points: Array<{high?: number; close?: number; value?: number}>}) =>
        item.points.reduce((max, point) => {
          const value = point.high ?? point.close ?? point.value
          return typeof value === 'number' && Number.isFinite(value) ? Math.max(max, Math.abs(value)) : max
        }, 0)
      const sessionPeak = Math.max(0, ...shownData.map(peakOf))
      const axisIndexFor = (item: {series: {key: string}; points: Array<{high?: number; close?: number; value?: number}>}) => {
        if (isSingle || axisMode === 'unified' || SMALL_AXIS_KEYS.has(item.series.key)) return 0
        if (BIG_AXIS_KEYS.has(item.series.key)) return 1
        return sessionPeak > 0 && peakOf(item) >= sessionPeak * BIG_AXIS_RATIO ? 1 : 0
      }

      /* 叠涨时该曲线按涨跌配色：折线分成两段，蜡烛线用涨跌色。 */
      const echartsSeries = shownData.map(item => {
        const color = colorFor(item)
        const riseFall = stackedRise && isActionPointSeries(item.series, ui('resource.ActionPoint'))
        if (isCandlestick) {
          const bucketMap = new Map(item.buckets.map(b => [b.time, b]))
          if (item.index === 0) {
            const candle = riseFall
              ? {color: rise, color0: fall, borderColor: rise, borderColor0: fall}
              : {color: primary, color0: secondary, borderColor: primary, borderColor0: secondary}
            return [{
              name: item.series.label, type: 'candlestick' as const, yAxisIndex: 0,
              itemStyle: candle,
              data: categoryTimes.map(t => { const b = bucketMap.get(t); return b ? [b.open, b.close, b.low, b.high] : '-' }),
            }]
          }
          return [{
            name: item.series.label, type: 'line' as const, yAxisIndex: axisIndexFor(item),
            showSymbol: item.points.length < 80, symbolSize: 5, connectNulls: true, lineStyle: {width: 2, color}, itemStyle: {color},
            data: categoryTimes.map(t => { const b = bucketMap.get(t); return b ? b.close : '-' }),
          }]
        }
        if (riseFall) {
          const segments = riseFallSegments(item.buckets.map(b => new Date(b.time.replace(' ', 'T')).getTime()), item.buckets.map(b => b.close))
          /* 拐点同属上涨与下跌两个系列，高亮会在同一坐标叠两个符号。 */
          return [
            {name: item.series.label, type: 'line' as const, yAxisIndex: axisIndexFor(item), showSymbol: false, connectNulls: false,
              emphasis: {disabled: true}, lineStyle: {width: 2, color: rise}, data: segments.rise},
            {name: item.series.label, type: 'line' as const, yAxisIndex: axisIndexFor(item), showSymbol: false, connectNulls: false,
              emphasis: {disabled: true}, lineStyle: {width: 2, color: fall}, data: padFall(segments.fall)},
          ]
        }
        return [{
          name: item.series.label, type: 'line' as const, yAxisIndex: axisIndexFor(item),
          showSymbol: item.points.length < 80, symbolSize: 5, connectNulls: false,
          /* 关闭悬停强调：相交处互相覆盖会看起来在闪。 */
          emphasis: {disabled: true},
          lineStyle: {width: 2, color}, itemStyle: {color},
          data: padPairs(item.buckets.map(b => [new Date(b.time.replace(' ', 'T')).getTime(), b.close] as [number, number])),
        }]
      }).flat()

      const hasRightAxis = !isSingle && axisMode === 'separate' && shownData.length >= 2

      chart.setOption({
        animation: false, textStyle: {color: text, fontFamily: 'Microsoft YaHei, sans-serif'},
        grid: {left: 65, right: hasRightAxis ? 65 : 30, top: !isSingle ? 80 : 65, bottom: 85},
        legend: !isSingle ? {show: true, top: 16, left: 'center', textStyle: {color: text}, data: shownData.map(item => item.series.label)} : undefined,
        tooltip: {
          trigger: 'axis', confine: true, renderMode: 'richText', axisPointer: {type: 'cross'},
          valueFormatter: (val: any) => typeof val === 'number' ? val.toLocaleString(undefined, {maximumFractionDigits: 2}) : String(val),
          ...(minimal ? {backgroundColor: surface, borderColor: border, textStyle: {color: text}, extraCssText: '', shadowBlur: 0} : {}),
        },
        toolbox: {
          right: 20,
          feature: {
            dataZoom: {yAxisIndex: 'none', title: {zoom: ui('stats.toolboxZoom'), back: ui('stats.toolboxBack')}},
            restore: {title: ui('stats.toolboxRestore')},
            saveAsImage: {title: ui('stats.toolboxSave'), name: shownData.map(item => item.series.label).join('-'), pixelRatio: 2},
          },
        },
        xAxis: isCandlestick ? {type: 'category', data: categoryTimes, axisLabel: {hideOverlap: true}} : {type: 'time', axisLabel: {hideOverlap: true}},
        yAxis: yAxes,
        /* 纵轴固定：缩放不过滤数据，纵轴始终按全量数据自动取值，与全图视角用同一套算法。 */
        dataZoom: [
          {type: 'inside', zoomOnMouseWheel: 'ctrl', filterMode: zeroBase ? 'none' : 'filter'},
          {
            type: 'slider', bottom: 16, height: 26, filterMode: zeroBase ? 'none' : 'filter',
            ...(minimal ? {
              backgroundColor: surface, fillerColor: colors.getPropertyValue('--accent-soft').trim(), borderColor: border,
              dataBackground: {lineStyle: {color: secondary, opacity: 1}, areaStyle: {color: surface, opacity: 1}},
              selectedDataBackground: {lineStyle: {color: primary, opacity: 1}, areaStyle: {color: colors.getPropertyValue('--accent-soft').trim(), opacity: 1}},
              handleStyle: {color: primary, borderColor: primary}, moveHandleStyle: {color: secondary},
            } : {}),
          },
        ],
        series: echartsSeries,
      }, true)
    }

    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) {
        event.stopPropagation()
      }
    }
    container.addEventListener('wheel', onWheel, {capture: true, passive: true})

    render()
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(element.current)
    const themeObserver = new MutationObserver(render)
    themeObserver.observe(document.documentElement, {attributes: true, /* 不监听 style：指针光效每次移动都写 --mx/--my，会把重绘拖进鼠标热路径并造成闪烁。 */
      attributeFilter: ['data-theme', 'data-palette', 'data-color-mode', 'style']})
    return () => {
      container.removeEventListener('wheel', onWheel, {capture: true})
      observer.disconnect()
      themeObserver.disconnect()
    }
  }, [shownData, hasPoints, isCandlestick, axisMode, isSingle, categoryTimes, category, language, ui, theme, stackedRise, zeroBase])


  /* 图表设置（类型、坐标轴、采样粒度、时间范围）排在图表下方：先看数据，再决定怎么画。 */
  const controls = <div className="statistics-controls">
    <label>
      {ui('stats.chart')}
      <Select
        aria-label={ui('stats.chartType')}
        value={mode}
        onChange={event => {
          const nextMode: ChartMode = event.target.value === 'candlestick' ? 'candlestick' : 'line'
          setMode(nextMode)
          if (nextMode === 'candlestick' && bucket === 0) {
            setBucket(60)
          }
        }}
      >
        <option value="line">{ui('stats.line')}</option>
        <option value="candlestick">{isSingle ? ui('stats.candlestick') : ui('stats.candlestickOverlay')}</option>
      </Select>
    </label>

    {!isSingle && (
      <label>
        {ui('stats.axisMode')}
        <Select aria-label={ui('stats.axisMode')} value={axisMode} onChange={event => setAxisMode(event.target.value as 'separate' | 'unified')}>
          <option value="separate">{ui('stats.axisSeparate')}</option>
          <option value="unified">{ui('stats.axisUnified')}</option>
        </Select>
      </label>
    )}


    <label>
      {ui('stats.bucket')}
      <Select aria-label={ui('stats.bucket')} value={effectiveBucket} onChange={event => setBucket(Number(event.target.value))}>
        {!isCandlestick && <option value={0}>{ui('stats.eachRecord')}</option>}
        <option value={5}>{ui('stats.fiveMinutes')}</option>
        <option value={60}>{ui('stats.hourly')}</option>
        <option value={1440}>{ui('stats.daily')}</option>
      </Select>
    </label>

    <label>
      {ui('stats.startTime')}
      <div className="date-input-wrap">
        <input type="datetime-local" aria-label={ui('stats.startTime')} value={from} className={from ? '' : 'date-empty'} onChange={event => setFrom(event.target.value)}/>
        {!from && <span className="date-input-placeholder" aria-hidden="true">---- / -- / --</span>}
      </div>
    </label>

    <label>
      {ui('stats.endTime')}
      <div className="date-input-wrap">
        <input type="datetime-local" aria-label={ui('stats.endTime')} value={to} className={to ? '' : 'date-empty'} onChange={event => setTo(event.target.value)}/>
        {!to && <span className="date-input-placeholder" aria-hidden="true">---- / -- / --</span>}
      </div>
    </label>

    <button className="text-button" onClick={() => {setFrom(''); setTo('')}}>{ui('stats.allTime')}</button>
  </div>

  const rangeError = from && to && from > to ? <p className="preview-error" role="alert">{ui('stats.invalidRange')}</p> : null


  /* 组合页里两张图卡标题相同、分不出是哪一张，带短名前缀后可以区分。 */
  const headingLabel = category === 'resources' ? ui('stats.chartHeading.resources') : category === 'action' ? ui('stats.chartHeading.action') : ui('stats.trendDetails')

  const chart = (
    <section className={`panel statistics-chart ${expanded ? 'chart-expanded' : ''}`}>
      {/* 紧凑主题把标题提到页面工具栏；放大视图盖住工具栏，此时必须把标题行放回来。 */}
      {(heading || expanded) && <div className="panel-heading">
        <h2>{expanded && title ? title : headingLabel}</h2>
        <div className="stat-card-actions">{foldControl}<button className="text-button" onClick={onToggleExpanded}>{expanded ? ui('stats.collapseChart') : ui('stats.expandChart')}</button></div>
      </div>}

      {showPicker ? <div className={`statistics-metrics-container${pickerMuted ? ' is-picker-muted' : ''}`}>
        <span className="statistics-metrics-label">{ui('stats.metric')}</span>
        <div className="statistics-metrics-chips" role="group" aria-label={ui('stats.metric')}>
          {series.map((item, idx) => {
            const active = selectedKeys.includes(item.key)
            const empty = item.points.length === 0
            const color = getSeriesColor(item.key, idx)
            const selectedIdx = selectedKeys.indexOf(item.key)
            const isCandlePrimary = active && isCandlestick && !isSingle && selectedIdx === 0
            const isOverlayLine = active && isCandlestick && !isSingle && selectedIdx > 0

            return (
              <button
                key={item.key} type="button"
                className={`stat-chip ${active ? 'active' : ''} ${empty ? 'empty' : ''}`}
                onClick={() => toggleKey(item.key)} onDoubleClick={() => selectOnly(item.key)}
                title={empty ? ui('stats.noSeriesRecord') : `${item.label} (${active ? '已启用' : '未启用'}，双击仅看此项)`}
                disabled={empty}
              >
                {getChartIcon(item) ? (
                  <img className="stat-chip-icon" src={getChartIcon(item)} alt="" width={20} height={20} draggable={false}/>
                ) : (
                  <span className="stat-chip-dot" style={{backgroundColor: active ? color : undefined}}/>
                )}
                <span>{item.label}</span>
                {isCandlePrimary && <span className="stat-chip-badge primary">{ui('stats.primaryCandle')}</span>}
                {isOverlayLine && (
                  <span className="stat-chip-badge secondary" title={ui('stats.setAsPrimary')} onClick={e => { e.stopPropagation(); setAsPrimary(item.key) }}>
                    {ui('stats.overlayLine')}
                  </span>
                )}
                {empty && <small>{ui('stats.noSeriesRecord')}</small>}
              </button>
            )
          })}
          {selectedKeys.length > 1 && (
            <button type="button" className="text-button" onClick={() => selectOnly(selectedKeys[0])}>{ui('stats.resetSelection')}</button>
          )}
          {compactControl}
          {stackedControl}
          {pickerControl}
          {zeroBaseControl}
        </div>
      </div> : null}

      {hasPoints ? (
        <>
          {isSingle ? (
            <div className="stat-metrics">
              {[[ui('stats.latest'), single.latest], [ui('stats.change'), single.change], [ui('stats.maximum'), single.maximum], [ui('stats.minimum'), single.minimum], [ui('stats.rawCount'), single.points.length]].map(([label, value]) => (
                <div key={String(label)}><span>{label}</span><strong>{Number(value).toLocaleString(undefined, {maximumFractionDigits: 2})}</strong></div>
              ))}
            </div>
          ) : (
            <div className={`stat-multi-metrics${compact ? ' is-compact' : ''}`}>
              {compact && <div className="stat-metric-labels" aria-hidden="true"><span/><span>{ui('stats.latest')}</span><span>{ui('stats.change')}</span><span>{ui('stats.maximum')}</span><span>{ui('stats.minimum')}</span></div>}
              {seriesData.map((item, idx) => {
                const diffClass = item.change > 0 ? 'positive' : item.change < 0 ? 'negative' : 'neutral'
                const formattedChange = item.change > 0 ? `+${item.change.toLocaleString(undefined, {maximumFractionDigits: 2})}` : item.change.toLocaleString(undefined, {maximumFractionDigits: 2})
                const isCandle = isCandlestick && idx === 0
                const muted = filtered.includes(item.series.key)
                /* 多于一个资源时才可点：否则会把唯一曲线也藏掉。 */
                const canFilter = selectedKeys.length > 1 && (muted || shownData.length > 1)
                const toggleFilter = () => onToggleFilter?.(item.series.key)
                const filterProps = canFilter ? {role: 'button' as const, tabIndex: 0, 'aria-pressed': !muted,
                  onClick: toggleFilter,
                  onKeyDown: (event: ReactKeyboardEvent<HTMLDivElement>) => {if (event.key === 'Enter' || event.key === ' ') {event.preventDefault(); toggleFilter()}}} : {}
                return compact ? (
                  <div key={item.series.key} className={`stat-metric-row${muted ? ' is-filtered' : ''}${canFilter ? ' is-filterable' : ''}`} {...filterProps}>
                    <span className="stat-metric-name">
                      <span className="stat-metric-icon">
                        {getChartIcon(item.series) ? (
                          <img className="stat-chip-icon" src={getChartIcon(item.series)} alt="" width={20} height={20} draggable={false}/>
                        ) : (
                          <span className="stat-chip-dot" style={{backgroundColor: item.color}}/>
                        )}
                      </span>
                      <strong>{item.series.label}{isCandle && <span className="stat-chip-badge primary">{ui('stats.primaryCandle')}</span>}</strong>
                    </span>
                    <span className="stat-metric-value">{item.latest == null ? '—' : item.latest.toLocaleString(undefined, {maximumFractionDigits: 2})}</span>
                    <strong className={`stat-metric-value ${diffClass}`}>{formattedChange}</strong>
                    <span className="stat-metric-value">{item.maximum.toLocaleString(undefined, {maximumFractionDigits: 2})}</span>
                    <span className="stat-metric-value">{item.minimum.toLocaleString(undefined, {maximumFractionDigits: 2})}</span>
                  </div>
                ) : (
                  <div key={item.series.key} className={`stat-metric-card${muted ? ' is-filtered' : ''}${canFilter ? ' is-filterable' : ''}`} {...filterProps}>
                    <div className="stat-metric-header">
                      {getChartIcon(item.series) ? (
                        <img className="stat-chip-icon" src={getChartIcon(item.series)} alt="" width={20} height={20} draggable={false}/>
                      ) : (
                        <span className="stat-chip-dot" style={{backgroundColor: item.color}}/>
                      )}
                      <strong>{item.series.label}{isCandle && <span className="stat-chip-badge primary">{ui('stats.primaryCandle')}</span>}</strong>
                    </div>
                    <div className="stat-metric-body">
                      <div><span>{ui('stats.latest')}</span><strong>{item.latest == null ? '—' : item.latest.toLocaleString(undefined, {maximumFractionDigits: 2})}</strong></div>
                      <div><span>{ui('stats.change')}</span><strong className={diffClass}>{formattedChange}</strong></div>
                      <div><span>{ui('stats.maximum')}</span><strong>{item.maximum.toLocaleString(undefined, {maximumFractionDigits: 2})}</strong></div>
                      <div><span>{ui('stats.minimum')}</span><strong>{item.minimum.toLocaleString(undefined, {maximumFractionDigits: 2})}</strong></div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}

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

  /* 放大态挂到 body：卡片链给每张卡设了 z-index，面板留在卡内会被顶栏盖住。 */
  return expanded ? createPortal(chart, document.body) : chart
}



