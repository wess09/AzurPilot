/**
 * 从 StatisticsChart.tsx 原 552-609 行提取，纯搬迁未改动。
 * 图表下方指标区：单序列摘要与多序列卡片/紧凑行。
 */
import type {KeyboardEvent as ReactKeyboardEvent} from 'react'
import { getChartIcon } from './chart-icons'
import type { ChartUi, SeriesDatumWithColor } from './shared'

export function buildChartMetrics({isSingle, single, seriesData, compact, filtered, selectedKeys, shownData, onToggleFilter, isCandlestick, ui}: {
  isSingle: boolean
  single: SeriesDatumWithColor
  seriesData: SeriesDatumWithColor[]
  compact: boolean
  filtered: string[]
  selectedKeys: string[]
  shownData: SeriesDatumWithColor[]
  onToggleFilter?: (key: string) => void
  isCandlestick: boolean
  ui: ChartUi
}) {
  return isSingle ? (
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
        // 多于一个资源时才可点：否则会把唯一曲线也藏掉。
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
  )
}
