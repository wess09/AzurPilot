/**
 * @fileoverview 图表表头选取器：系列芯片、K 线主次标记与表头容器内的开关。
 * 从 StatisticsChart.tsx 原 504-548 行提取，纯搬迁未改动。
 */
import type {ReactNode} from 'react'
import { Button } from '../ui/button'
import { getSeriesColor } from './chart-colors'
import { getChartIcon } from './chart-icons'
import type { ChartUi } from './shared'
import type {StatSeries} from '../../api/types'

/** 组装图表表头选取器：系列芯片与类型/堆叠等开关的容器。 */
export function buildChartPicker({series, selectedKeys, toggleKey, selectOnly, setAsPrimary, isCandlestick, isSingle, ui, compactControl, stackedControl, pickerControl, zeroBaseControl, pickerMuted, showPicker}: {
  series: StatSeries[]
  selectedKeys: string[]
  toggleKey: (key: string) => void
  selectOnly: (key: string) => void
  setAsPrimary: (key: string) => void
  isCandlestick: boolean
  isSingle: boolean
  ui: ChartUi
  compactControl?: ReactNode
  stackedControl?: ReactNode
  pickerControl?: ReactNode
  zeroBaseControl?: ReactNode
  pickerMuted: boolean
  showPicker: boolean
}) {
  return showPicker ? <div className={`statistics-metrics-container${pickerMuted ? ' is-picker-muted' : ''}`}>
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
          <Button
            key={item.key} type="button"
            className={`stat-chip ${active ? 'active' : ''} ${empty ? 'empty' : ''}`}
            size="sm" variant={active ? 'default' : 'outline'} aria-pressed={active}
            onClick={() => toggleKey(item.key)} onDoubleClick={() => selectOnly(item.key)}
            title={empty ? ui('stats.noSeriesRecord') : ui(active ? 'stats.chipActive' : 'stats.chipInactive', {label: item.label})}
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
          </Button>
        )
      })}
      {selectedKeys.length > 1 && (
        <Button type="button" variant="ghost" size="sm" onClick={() => {
          const firstKey = selectedKeys[0]
          if (firstKey !== undefined) selectOnly(firstKey)
        }}>{ui('stats.resetSelection')}</Button>
      )}
      {compactControl}
      {stackedControl}
      {pickerControl}
      {zeroBaseControl}
    </div>
  </div> : null
}
