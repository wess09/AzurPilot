import { Select } from './FormControls'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { LineChart, CandlestickChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, DataZoomComponent, ToolboxComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { StatSeries } from '../api/types'
import { Empty } from './ui'
import { StatisticsTable } from './StatisticsTable'
import { aggregatePoints } from './statisticsData'
import { useApp } from '../app/context'
import { usesMaterial } from '../app/theme'

echarts.use([LineChart, CandlestickChart, GridComponent, TooltipComponent, DataZoomComponent, ToolboxComponent, CanvasRenderer])

export function StatisticsChart({series}: {series: StatSeries[]}) {
  const {ui, language, theme} = useApp()
  const [key, setKey] = useState(series.find(item => item.points.length)?.key ?? series[0]?.key ?? '')
  const [mode, setMode] = useState('line')
  const [bucket, setBucket] = useState(0)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [expanded, setExpanded] = useState(false)
  useEffect(() => {
    if (!expanded) return
    const close = (event: KeyboardEvent) => {if (event.key === 'Escape') setExpanded(false)}
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [expanded])
  const element = useRef<HTMLDivElement>(null)
  const current = series.find(item => item.key === key) ?? series[0]
  const points = useMemo(() => (current?.points ?? []).filter(point => (!from || point.time.replace(' ', 'T') >= from) && (!to || point.time.replace(' ', 'T') <= `${to}:59.999`)), [current, from, to])
  const buckets = useMemo(() => aggregatePoints(points, bucket || (mode === 'candlestick' ? 60 : 0)), [points, bucket, mode])
  const values = points.map(point => point.value)
  const minimum = values.length ? Math.min(...values) : 0
  const maximum = values.length ? Math.max(...values) : 0
  useEffect(() => {
    if (!element.current || !points.length) return
    const chart = echarts.init(element.current, undefined, {locale: language.startsWith('zh') ? 'ZH' : 'EN'})
    function render() {
      const colors = getComputedStyle(document.documentElement)
      const text = colors.getPropertyValue('--text').trim() || '#82929f'
      const minimal = !usesMaterial(theme)
      const primary = minimal ? colors.getPropertyValue('--accent').trim() : '#159b88'
      const secondary = minimal ? colors.getPropertyValue('--secondary').trim() : '#de7861'
      const surface = colors.getPropertyValue('--surface').trim()
      const border = colors.getPropertyValue('--border').trim()
      chart.setOption({
        animation: false, textStyle: {color: text, fontFamily: 'Microsoft YaHei, sans-serif'},
        grid: {left: 65, right: 30, top: 65, bottom: 85},
        tooltip: {trigger: 'axis', confine: true, renderMode: 'richText', axisPointer: {type: 'cross'}, ...(minimal ? {backgroundColor: surface, borderColor: border, textStyle: {color: text}, extraCssText: '', shadowBlur: 0} : {})},
        toolbox: {right: 20, feature: {dataZoom: {yAxisIndex: 'none', title: {zoom: ui('stats.toolboxZoom'), back: ui('stats.toolboxBack')}}, restore: {title: ui('stats.toolboxRestore')}, saveAsImage: {title: ui('stats.toolboxSave'), name: current.label, pixelRatio: 2}}},
        xAxis: mode === 'candlestick' ? {type: 'category', data: buckets.map(item => item.time), axisLabel: {hideOverlap: true}} : {type: 'time', axisLabel: {hideOverlap: true}},
        yAxis: {type: 'value', scale: true, splitLine: {lineStyle: {color: colors.getPropertyValue('--border').trim()}}},
        dataZoom: [{type: 'inside', zoomOnMouseWheel: 'ctrl'}, {type: 'slider', bottom: 16, height: 26, ...(minimal ? {backgroundColor: surface, fillerColor: colors.getPropertyValue('--accent-soft').trim(), borderColor: border, dataBackground: {lineStyle: {color: secondary, opacity: 1}, areaStyle: {color: surface, opacity: 1}}, selectedDataBackground: {lineStyle: {color: primary, opacity: 1}, areaStyle: {color: colors.getPropertyValue('--accent-soft').trim(), opacity: 1}}, handleStyle: {color: primary, borderColor: primary}, moveHandleStyle: {color: secondary}} : {})}],
        series: [{name: current.label, type: mode === 'candlestick' ? 'candlestick' : 'line',
          showSymbol: points.length < 80, symbolSize: 5, connectNulls: false,
          lineStyle: {width: 2}, itemStyle: mode === 'candlestick' ? {color: primary, color0: secondary, borderColor: primary, borderColor0: secondary} : {color: primary},
          data: buckets.map(item => mode === 'candlestick' ? [item.open, item.close, item.low, item.high] : [new Date(item.time.replace(' ', 'T')).getTime(), item.close]),
        }],
      }, true)
    }
    render()
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(element.current)
    // 命名避开上下文里的 theme，否则 render() 会读到这个后来才初始化的绑定。
    const themeObserver = new MutationObserver(render)
    themeObserver.observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme', 'data-palette', 'data-color-mode', 'style']})
    return () => {observer.disconnect(); themeObserver.disconnect(); chart.dispose()}
  }, [points, buckets, mode, current.label, language, ui, theme])
  return <section className={`panel statistics-chart ${expanded ? 'chart-expanded' : ''}`}>
    <div className="panel-heading"><h2>{ui('stats.trendDetails')}</h2><button className="text-button" onClick={() => setExpanded(!expanded)}>{expanded ? ui('stats.collapseChart') : ui('stats.expandChart')}</button></div>
    <div className="statistics-controls"><label>{ui('stats.metric')}<Select aria-label={ui('stats.metric')} value={current.key} onChange={event => setKey(event.target.value)}>{series.map(item => <option value={item.key} key={item.key}>{item.label}{item.points.length ? '' : ui('stats.noSeriesRecord')}</option>)}</Select></label>
      <label>{ui('stats.chart')}<Select aria-label={ui('stats.chartType')} value={mode} onChange={event => setMode(event.target.value)}><option value="line">{ui('stats.line')}</option><option value="candlestick">{ui('stats.candlestick')}</option></Select></label>
      <label>{ui('stats.bucket')}<Select aria-label={ui('stats.bucket')} value={bucket} onChange={event => setBucket(Number(event.target.value))}><option value={0}>{mode === 'candlestick' ? ui('stats.hourly') : ui('stats.eachRecord')}</option><option value={5}>{ui('stats.fiveMinutes')}</option><option value={60}>{ui('stats.hourly')}</option><option value={1440}>{ui('stats.daily')}</option></Select></label>
      <label>{ui('stats.startTime')}<div className="date-input-wrap"><input type="datetime-local" aria-label={ui('stats.startTime')} value={from} className={from ? '' : 'date-empty'} onChange={event => setFrom(event.target.value)}/>{!from && <span className="date-input-placeholder" aria-hidden="true">---- / -- / --</span>}</div></label><label>{ui('stats.endTime')}<div className="date-input-wrap"><input type="datetime-local" aria-label={ui('stats.endTime')} value={to} className={to ? '' : 'date-empty'} onChange={event => setTo(event.target.value)}/>{!to && <span className="date-input-placeholder" aria-hidden="true">---- / -- / --</span>}</div></label><button className="text-button" onClick={() => {setFrom(''); setTo('')}}>{ui('stats.allTime')}</button></div>
    {from && to && from > to && <p className="preview-error" role="alert">{ui('stats.invalidRange')}</p>}
    {points.length ? <><div className="stat-metrics">{[[ui('stats.latest'), values.at(-1)], [ui('stats.change'), values.at(-1)! - values[0]], [ui('stats.maximum'), maximum], [ui('stats.minimum'), minimum], [ui('stats.rawCount'), points.length]].map(([label, value]) => <div key={String(label)}><span>{label}</span><strong>{Number(value).toLocaleString(undefined, {maximumFractionDigits: 2})}</strong></div>)}</div><div ref={element} className="chart-canvas" role="img" aria-label={ui('stats.chartAria', {label: current.label})}/><p className="panel-note">{ui('stats.chartHint')}</p><StatisticsTable data={{title: ui('stats.rawTitle', {label: current.label}), columns: [ui('stats.time'), ui('stats.value'), ui('stats.source')], rows: points.map(point => [point.time, point.value, point.source || '—']), defaultSort: {index: 0, descending: true}}}/></> : <Empty title={ui('stats.noValidTitle')}>{ui('stats.noValidHint')}</Empty>}
  </section>
}
