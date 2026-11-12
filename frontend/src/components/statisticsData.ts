/**
 * @fileoverview 统计数据聚合、图表计算与表格排序辅助工具。
 */

import type { StatSeries,  Scalar, StatPoint, StatisticsReport, StatisticsReportWire } from '../api/types'
import type { ChartMode } from '../app/statisticsPrefs'

/** 把点位按 minutes 分钟聚成开高低收桶：时间截断到桶起点；1440 表示按天（零点对齐），0 表示不聚合、逐点透传。 */
export function aggregatePoints(points: StatPoint[], minutes: number) {
  const buckets = new Map<string, {time: string; open: number; close: number; low: number; high: number}>()
  for (const [index, point] of points.entries()) {
    const date = new Date(point.time.replace(' ', 'T'))
    if (!Number.isFinite(date.getTime()) || !Number.isFinite(point.value)) continue
    if (minutes === 1440) date.setHours(0, 0, 0, 0)
    else if (minutes) date.setMinutes(Math.floor(date.getMinutes() / minutes) * minutes, 0, 0)
    const key = minutes ? String(date.getTime()) : String(index)
    const previous = buckets.get(key)
    if (previous) { previous.close = point.value; previous.low = Math.min(previous.low, point.value); previous.high = Math.max(previous.high, point.value) }
    else buckets.set(key, {time: minutes ? `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}:00` : point.time, open: point.value, close: point.value, low: point.value, high: point.value})
  }
  return [...buckets.values()]
}

/** 把二维表下载为 CSV 文件（自动补 .csv 后缀）：加 BOM 兼容 Excel 读 UTF-8，行尾用 CRLF。 */
export function downloadCsv(name: string, rows: Scalar[][]) {
  const escape = (value: Scalar) => {
    let text = value == null ? '' : String(value)
    // 文本单元格禁用公式解释，保留数值负号的正常语义。
    if (typeof value === 'string' && /^[=+\-@\t\r]/.test(text)) text = `'${text}`
    return `"${text.replaceAll('"', '""')}"`
  }
  const url = URL.createObjectURL(new Blob(['\uFEFF' + rows.map(row => row.map(escape).join(',')).join('\r\n')], {type: 'text/csv;charset=utf-8'}))
  const link = document.createElement('a'); link.href = url; link.download = `${name}.csv`; link.click(); URL.revokeObjectURL(url)
}

/** 把多条系列按时刻对齐成表格行：一行一时刻、各系列一列，缺值补 '—'，末列为来源；时间倒序，from/to 为空表示不限。 */
export function mergeMultiSeriesRows(
  seriesList: {key: string; label: string; points: StatPoint[]}[],
  from = '',
  to = '',
): Scalar[][] {
  const timeMap = new Map<string, {values: Record<string, number>; source: string}>()
  for (const s of seriesList) {
    for (const p of s.points) {
      const t = p.time.replace(' ', 'T')
      if (from && t < from) continue
      if (to && t > `${to}:59.999`) continue
      const existing = timeMap.get(p.time)
      if (existing) {
        existing.values[s.key] = p.value
        if (!existing.source && p.source) existing.source = p.source
      } else {
        timeMap.set(p.time, {values: {[s.key]: p.value}, source: p.source ?? ''})
      }
    }
  }
  const sortedTimes = [...timeMap.keys()].sort((a, b) => b.localeCompare(a))
  return sortedTimes.map(time => {
    const entry = timeMap.get(time)!
    return [
      time,
      ...seriesList.map(s => (entry.values[s.key] != null ? entry.values[s.key] : '—')),
      entry.source || '—',
    ]
  })
}

/** 图表与原始记录表共用的视图：同一份选中、聚合与时间范围，两边各自算出同一结果。 */
interface StatisticsView {
  selectedSeries: StatSeries[]
  seriesData: {
    series: StatSeries
    points: StatPoint[]
    buckets: ReturnType<typeof aggregatePoints>
    values: number[]
    latest?: number
    change: number
    minimum: number
    maximum: number
  }[]
  isSingle: boolean
  effectiveBucket: number
  mergedRows: Scalar[][]
}

/* 选中系列按保存顺序排列；没有可用记录时取第一条有数据的系列。 */
function resolveSelectedKeys(series: StatSeries[], saved: string[]): string[] {
  const valid = saved.filter(key => series.some(item => item.key === key))
  if (valid.length) return valid
  const active = series.find(item => item.points.length)?.key ?? series[0]?.key
  return active ? [active] : []
}

/** 算出图表与原始记录表共用的视图：按保存顺序取选中的系列，桶与统计值随模式与聚合粒度变化（蜡烛图下粒度 0 视作 60 分钟）；单系列表格直接用原点位，多系列按时刻合并。 */
export function buildSeriesView(series: StatSeries[], options: {selectedKeys: string[]; mode: ChartMode; bucket: number; from: string; to: string}): StatisticsView {
  const {selectedKeys, mode, bucket, from, to} = options
  const keys = resolveSelectedKeys(series, selectedKeys)
  const selectedSeries = keys.map(key => series.find(item => item.key === key)!).filter(Boolean)
  const isSingle = selectedSeries.length === 1
  const effectiveBucket = mode === 'candlestick' && bucket === 0 ? 60 : bucket
  const seriesData = selectedSeries.map(s => {
    const points = s.points.filter(point => (!from || point.time.replace(' ', 'T') >= from) && (!to || point.time.replace(' ', 'T') <= `${to}:59.999`))
    const values = points.map(p => p.value)
    return {
      series: s, points, buckets: aggregatePoints(points, effectiveBucket), values,
      latest: values.at(-1),
      change: values.length >= 2 ? (values.at(-1)! - values[0]) : 0,
      minimum: values.length ? Math.min(...values) : 0,
      maximum: values.length ? Math.max(...values) : 0,
    }
  })
  const single = seriesData[0]
  const mergedRows = isSingle && single
    ? single.points.map(point => [point.time, point.value, point.source || '—'] as Scalar[])
    : mergeMultiSeriesRows(selectedSeries, from, to)
  return {selectedSeries, seriesData, isSingle, effectiveBucket, mergedRows}
}

/**
 * 涨跌分段：相邻两点之间按方向归入上涨（持平并入上涨）与下跌两组，组间用 '-' 断开，
 * 这样每组是一条独立折线，可以各自上色。
 */
export function riseFallSegments(times: number[], closes: (number | null)[]): {rise: (number[] | '-')[]; fall: (number[] | '-')[]} {
  const rise: (number[] | '-')[] = []
  const fall: (number[] | '-')[] = []
  const deltas = riseFallDeltas(closes)
  for (let index = 1; index < closes.length; index += 1) {
    const previous = closes[index - 1]
    const current = closes[index]
    if (previous == null || current == null) continue
    const target = deltas[index] >= 0 ? rise : fall
    target.push([times[index - 1], previous], [times[index], current], '-')
  }
  return {rise, fall}
}

/** 行动力这条曲线：键固定为 ap，标签作兜底（各页面的资源标签来自后端）。 */
export function isActionPointSeries(series: {key: string; label: string}, label: string): boolean {
  return series.key === 'ap' || series.label === label
}

/** 逐点涨跌：与前一点比较，涨为正、跌为负；首点与空值没有可比值，记 0。 */
export function riseFallDeltas(values: (number | null)[]): number[] {
  return values.map((value, index) => {
    const previous = index > 0 ? values[index - 1] : null
    if (value == null || previous == null) return 0
    return value - previous
  })
}

/** 微秒整数还原为墙上时钟文本，与原格式逐字一致。 */
const wallClock = (micros: number) => {
  const seconds = Math.floor(micros / 1000000)
  const fraction = micros - seconds * 1000000
  const date = new Date(seconds * 1000)
  const pad = (value: number, width = 2) => String(value).padStart(width, '0')
  const base = `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ` +
    `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}`
  return fraction ? `${base}.${pad(fraction, 6)}` : base
}

/** 把传输用的紧凑点还原成内部点位。 */
export function normalizeReport(report: StatisticsReportWire): StatisticsReport {
  const {axis, series, ...rest} = report
  return {
    ...rest,
    series: series.map(item => 'values' in item
      ? {key: item.key, label: item.label, icon: item.icon, points: item.values.map((value, index) => ({
        time: wallClock(axis![index]), value, source: item.sources?.[index] ?? '',
      }))}
      : {key: item.key, label: item.label, icon: item.icon, points: item.points.map(point => ({
        time: wallClock(point.t), value: point.v, source: point.s ?? '',
      }))}),
  }
}
