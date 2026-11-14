/**
 * 从 StatisticsChart.tsx 原 247-431 行提取，纯搬迁未改动。
 * ECharts 画布渲染副作用：主题监听、轴配置、涨跌分段与缩放控件。
 */
import { useEffect, type RefObject } from 'react'
import * as echarts from 'echarts/core'
import { isActionPointSeries, riseFallSegments } from '../statisticsData'
import type { ChartAxisMode } from '../../app/statisticsPrefs'
import type { ChartUi, SeriesDatumWithColor } from './shared'

export function useChartRender({element, seriesData, shownData, hasPoints, isCandlestick, axisMode, isSingle, categoryTimes, category, language, ui, theme, stackedRise, zeroBase}: {
  element: RefObject<HTMLDivElement | null>
  seriesData: SeriesDatumWithColor[]
  shownData: SeriesDatumWithColor[]
  hasPoints: boolean
  isCandlestick: boolean
  axisMode: ChartAxisMode
  isSingle: boolean
  categoryTimes: string[]
  category: string
  language: string
  ui: ChartUi
  theme: string
  stackedRise: boolean
  zeroBase: boolean
}) {
  useEffect(() => {
    if (!element.current || !hasPoints) return
    const container = element.current
    const chart = echarts.getInstanceByDom(container) ?? echarts.init(container, undefined, {locale: language.startsWith('zh') ? 'ZH' : 'EN'})

    // 重绘只取决于下面这几个 CSS 变量。这个观察者还会被与图表无关的 <html> style
    // 写入触发（例如指针光效的 --mx/--my），所以先比签名再决定要不要重建。
    let renderedSignature = ''
    function render() {
      const colors = getComputedStyle(document.documentElement)
      const text = colors.getPropertyValue('--text').trim() || '#82929f'
      const primary = colors.getPropertyValue('--theme-chart-primary').trim() || colors.getPropertyValue('--accent').trim()
      const secondary = colors.getPropertyValue('--theme-chart-secondary').trim() || colors.getPropertyValue('--secondary').trim()
      const rise = colors.getPropertyValue('--theme-chart-rise').trim() || '#dc2626'
      const fall = colors.getPropertyValue('--theme-chart-fall').trim() || '#16a34a'
      // 网格线只铺在图表内部那张二级面上，透明度跟随它的不透明度。
      const gridOpacity = Math.min(1, Math.max(0, (parseFloat(colors.getPropertyValue('--theme-plate-alpha')) || 100) / 100))
      const surface = colors.getPropertyValue('--surface').trim()
      const border = colors.getPropertyValue('--border').trim()
      const accentSoft = colors.getPropertyValue('--accent-soft').trim()
      const signature = `${theme}|${text}|${primary}|${secondary}|${rise}|${fall}|${surface}|${border}|${accentSoft}|${gridOpacity}`
      if (signature === renderedSignature) return
      renderedSignature = signature
      const colorFor = (item: typeof seriesData[number]) => isSingle ? primary : item.color
      // 观感补全用的整图时间跨度。
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
      // 只补绘制用的点，不改数据、指标与记录。
      const padPairs = (pairs: Array<[number, number]>): Array<[number, number]> => {
        if (category === 'storage' || !padRange || pairs.length === 0) return pairs
        const padded: Array<[number, number]> = [...pairs]
        if (padded[0][0] > axisStart) padded.unshift([axisStart, 0])
        const last = padded[padded.length - 1]
        if (last[0] < axisEnd) padded.push([axisEnd, last[1]])
        return padded
      }
      // 涨跌分段模式下只补下跌段。
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


      // 纵轴固定：下界钉在 0，上界仍由 ECharts 按全量数据算，与「从 0 开始的自适应」同解。
      if (zeroBase) yAxes = yAxes.map(axis => ({...axis, min: 0}))

      // 每条曲线落在哪个 Y 轴上：单页与统一轴都用左轴。
      // 大小轴归属：左轴小值、右轴大值。
      const BIG_AXIS_KEYS = new Set(['asset', 'yellow_coins', 'distance'])
      const SMALL_AXIS_KEYS = new Set(['ap', 'purple_coins'])
      const BIG_AXIS_RATIO = 0.05 // 峰值达到全场峰值的 5% 才占右轴
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

      // 叠涨时该曲线按涨跌配色：折线分成两段，蜡烛线用涨跌色。
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
          // 拐点同属上涨与下跌两个系列，高亮会在同一坐标叠两个符号。
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
          // 关闭悬停强调：相交处互相覆盖会看起来在闪。
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
          backgroundColor: surface, borderColor: border, textStyle: {color: text}, extraCssText: '', shadowBlur: 0,
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
        // 纵轴固定：缩放不过滤数据，纵轴始终按全量数据自动取值，与全图视角用同一套算法。
        dataZoom: [
          {type: 'inside', zoomOnMouseWheel: 'ctrl', filterMode: zeroBase ? 'none' : 'filter'},
          {
            type: 'slider', bottom: 16, height: 26, filterMode: zeroBase ? 'none' : 'filter',
            backgroundColor: surface, fillerColor: colors.getPropertyValue('--accent-soft').trim(), borderColor: border,
            dataBackground: {lineStyle: {color: secondary, opacity: 1}, areaStyle: {color: surface, opacity: 1}},
            selectedDataBackground: {lineStyle: {color: primary, opacity: 1}, areaStyle: {color: colors.getPropertyValue('--accent-soft').trim(), opacity: 1}},
            handleStyle: {color: primary, borderColor: primary}, moveHandleStyle: {color: secondary},
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
    themeObserver.observe(document.documentElement, {attributeFilter: ['data-theme', 'style']})
    return () => {
      container.removeEventListener('wheel', onWheel, {capture: true})
      observer.disconnect()
      themeObserver.disconnect()
    }
  }, [shownData, hasPoints, isCandlestick, axisMode, isSingle, categoryTimes, category, language, ui, theme, stackedRise, zeroBase])
}
