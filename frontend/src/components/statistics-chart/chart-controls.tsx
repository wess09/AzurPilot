/**
 * 从 StatisticsChart.tsx 原 434-491 行提取，纯搬迁未改动。
 * 图表设置控件：类型、坐标轴、采样粒度、时间范围与校验提示。
 */
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../official-ui/select'
import { Input } from '../official-ui/input'
import { Button } from '../ui/button'
import { bucketOptions } from './shared'
import type { ChartUi } from './shared'
import type { ChartMode, ChartAxisMode } from '../../app/statisticsPrefs'

export function buildChartControls({ui, mode, setMode, bucket, setBucket, axisMode, setAxisMode, effectiveBucket, isCandlestick, isSingle, from, setFrom, to, setTo}: {
  ui: ChartUi
  mode: ChartMode
  setMode: (next: ChartMode) => void
  bucket: number
  setBucket: (next: number) => void
  axisMode: ChartAxisMode
  setAxisMode: (next: 'separate' | 'unified') => void
  effectiveBucket: number
  isCandlestick: boolean
  isSingle: boolean
  from: string
  setFrom: (next: string) => void
  to: string
  setTo: (next: string) => void
}) {
  // 图表设置（类型、坐标轴、采样粒度、时间范围）排在图表下方：先看数据，再决定怎么画。
  const controls = <div className="statistics-controls">
    <label>
      {ui('stats.chart')}
      <Select
        value={mode}
        onValueChange={value => {
          const nextMode: ChartMode = value === 'candlestick' ? 'candlestick' : 'line'
          setMode(nextMode)
          if (nextMode === 'candlestick' && bucket === 0) {
            setBucket(60)
          }
        }}
      >
        <SelectTrigger aria-label={ui('stats.chartType')}><SelectValue/></SelectTrigger>
        <SelectContent><SelectItem value="line">{ui('stats.line')}</SelectItem><SelectItem value="candlestick">{isSingle ? ui('stats.candlestick') : ui('stats.candlestickOverlay')}</SelectItem></SelectContent>
      </Select>
    </label>

    {!isSingle && (
      <label>
        {ui('stats.axisMode')}
        <Select value={axisMode} onValueChange={value => setAxisMode(value as 'separate' | 'unified')}>
          <SelectTrigger aria-label={ui('stats.axisMode')}><SelectValue/></SelectTrigger>
          <SelectContent><SelectItem value="separate">{ui('stats.axisSeparate')}</SelectItem><SelectItem value="unified">{ui('stats.axisUnified')}</SelectItem></SelectContent>
        </Select>
      </label>
    )}


    <label>
      {ui('stats.bucket')}
      <Select value={String(effectiveBucket)} onValueChange={value => setBucket(Number(value))}>
        <SelectTrigger aria-label={ui('stats.bucket')}><SelectValue/></SelectTrigger>
        <SelectContent>{bucketOptions(isCandlestick, ui).map(option => <SelectItem key={option.value} value={String(option.value)}>{option.label}</SelectItem>)}</SelectContent>
      </Select>
    </label>

    <label>
      {ui('stats.startTime')}
      <div className="date-input-wrap">
        <Input type="datetime-local" aria-label={ui('stats.startTime')} value={from} onChange={event => setFrom(event.target.value)}/>
        {!from && <span className="date-input-placeholder" aria-hidden="true">---- / -- / --</span>}
      </div>
    </label>

    <label>
      {ui('stats.endTime')}
      <div className="date-input-wrap">
        <Input type="datetime-local" aria-label={ui('stats.endTime')} value={to} onChange={event => setTo(event.target.value)}/>
        {!to && <span className="date-input-placeholder" aria-hidden="true">---- / -- / --</span>}
      </div>
    </label>

    <Button variant="ghost" onClick={() => {setFrom(''); setTo('')}}>{ui('stats.allTime')}</Button>
  </div>

  const rangeError = from && to && from > to ? <p className="preview-error" role="alert">{ui('stats.invalidRange')}</p> : null
  return {controls, rangeError}
}
