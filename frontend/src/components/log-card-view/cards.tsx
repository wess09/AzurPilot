/**
 * @fileoverview 日志卡片域的透视、表格、热力矩阵、横幅与单行卡片组件。
 * 从 LogCardView.tsx 原 1081-1273、1615-1892 行提取，纯搬迁未改动。
 */

import {
  memo,
  useMemo,
  useState,
  type CSSProperties,
  type ReactNode,
} from 'react'
import {
  AlertCircle,
  Ban,
  ChevronDown,
  ChevronRight,
  Compass,
  Crown,
  Layers,
  Map as MapIcon,
  Package,
  PawPrint,
  Radar,
  Ship,
  Sparkles,
  Swords,
  Table as TableIcon,
} from 'lucide-react'
import { LazyMarkdown } from '../LazyMarkdown'
import type { CardItem } from './aggregate'
import { getCellMeta, renderCellContent } from './map-grid'
import { CopyButton } from './shared'
import { renderTokens } from './tokens'

/** 海域透视卡片：SVG 梯形示意四条边界的完整度，附水平/垂直识别指标。 */
const PerspectiveCard = memo(
  function PerspectiveCard({ card }: { card: Extract<CardItem, { type: 'perspective' }> }) {
    const allActive = card.leftEdge && card.upperEdge && card.rightEdge && card.lowerEdge

    return (
      <div className={`log-card perspective-card ${allActive ? 'perspective-complete' : 'perspective-has-missing'}`}>
        <div className="card-header">
          <div className="card-title">
            <Compass size={16} className={allActive ? 'text-secondary' : 'text-warning'} />
            <span className="title-bold">海域{card.model}与边界线拓扑</span>
            <span className="badge-pill duration">{card.duration}</span>
            <span className="card-time">{card.time}</span>
          </div>
          <div className="card-actions">
            <CopyButton text={card.rawText} />
          </div>
        </div>
        <div className="card-body perspective-body">
          {/* 梯形视口微型几何模型（向前倾斜，近大远小） */}
          <div className="trapezoid-visual" title="海域 2.5D 透视边界视口 (向前倾斜)">
            <svg width="156" height="80" viewBox="0 0 156 80" className="trapezoid-svg">
              {/* 梯形底面浅色半透明背景（仅完全闭合时填充） */}
              <polygon
                points="44,14 112,14 144,68 12,68"
                className={`trapezoid-fill ${allActive ? 'fill-all' : 'fill-broken'}`}
              />
              {/* 纵深透视虚线网格（向前方地平线收拢） */}
              <line x1="60" y1="14" x2="48" y2="68" className="grid-depth-line" />
              <line x1="78" y1="14" x2="78" y2="68" className="grid-depth-line" />
              <line x1="96" y1="14" x2="108" y2="68" className="grid-depth-line" />
              <line x1="28" y1="41" x2="128" y2="41" className="grid-depth-line" />

              {/* 上边界（远处，较短） */}
              <line
                x1="44" y1="14" x2="112" y2="14"
                className={`edge-stroke ${card.upperEdge ? 'edge-active' : 'edge-missing'}`}
              />

              {/* 下边界（近处，较宽） */}
              <line
                x1="12" y1="68" x2="144" y2="68"
                className={`edge-stroke ${card.lowerEdge ? 'edge-active' : 'edge-missing'}`}
              />

              {/* 左边界（向前倾斜收拢） */}
              <line
                x1="12" y1="68" x2="44" y2="14"
                className={`edge-stroke ${card.leftEdge ? 'edge-active' : 'edge-missing'}`}
              />

              {/* 右边界（向前倾斜收拢） */}
              <line
                x1="112" y1="14" x2="144" y2="68"
                className={`edge-stroke ${card.rightEdge ? 'edge-active' : 'edge-missing'}`}
              />
            </svg>
          </div>

          {/* 识别指标清单 */}
          <div className="perspective-metrics">
            <div className="metric-row">
              <span className="metric-label">水平状态:</span>
              <span className="metric-val">{card.info1}</span>
            </div>
            <div className="metric-row">
              <span className="metric-label">垂直/定位:</span>
              <span className="metric-val">{card.info2}</span>
            </div>
          </div>
        </div>
      </div>
    )
  },
  (prev, next) => prev.card === next.card
)

/** 属性清单卡片：连续的 key: value 行排成两列网格。 */
const PropertySheetCard = memo(
  function PropertySheetCard({ card, search }: { card: Extract<CardItem, { type: 'property_sheet' }>; search: string }) {
    return (
      <div className="log-card property-card">
        <div className="card-header">
          <div className="card-title">
            <Layers size={15} className="text-muted" />
            <span className="title-bold">状态属性清单</span>
            <span className="card-time">{card.time}</span>
          </div>
          <div className="card-actions">
            <CopyButton text={card.rawText} />
          </div>
        </div>
        <div className="card-body">
          <div className="property-grid">
            {card.items.map((item, idx) => (
              <div key={idx} className="property-row">
                <span className="prop-key">{item.key}</span>
                <span className="prop-divider">:</span>
                <span className="prop-val">{renderTokens(item.value, search)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    )
  },
  (prev, next) => prev.card === next.card && prev.search === next.search
)

function renderTableCell(cell: string): ReactNode {
  const trimmed = cell.trim()
  if (trimmed === 'PASS' || trimmed === 'Fastest') {
    return <span style={{ color: '#22c55e', fontWeight: 600 }}>{cell}</span>
  }
  if (trimmed === 'Warning' || trimmed === 'Medium') {
    return <span style={{ color: '#eab308', fontWeight: 600 }}>{cell}</span>
  }
  if (trimmed === 'Failed' || trimmed === 'Error' || trimmed === 'Slow') {
    return <span style={{ color: '#ef4444', fontWeight: 600 }}>{cell}</span>
  }
  if (trimmed === 'T0') {
    return <span style={{ color: '#f59e0b', fontWeight: 700 }}>{cell}</span>
  }
  if (trimmed === 'T1') {
    return <span style={{ color: '#8b5cf6', fontWeight: 600 }}>{cell}</span>
  }
  return cell
}

/** 数据表格卡片：Rich/ASCII 表格还原成原生表格，列对齐按数字占比推断。 */
const DataTableCard = memo(
  function DataTableCard({ card }: { card: Extract<CardItem, { type: 'data_table' }> }) {
    // 智能推断列对齐方式：若该列非空值多为数字或测量单位，则右对齐，否则左对齐。
    const colAlignments = useMemo(() => {
      return card.headers.map((_, cIdx) => {
        let numericCount = 0
        let totalCount = 0
        for (const row of card.rows) {
          const val = row[cIdx]?.trim() || ''
          if (val) {
            totalCount++
            if (/^[-+]?[\d.,]+([a-zA-Z%]+|\/[0-9]+)?$/.test(val)) {
              numericCount++
            }
          }
        }
        return totalCount > 0 && numericCount / totalCount >= 0.6 ? 'right' : 'left'
      })
    }, [card.headers, card.rows])

    return (
      <div className="log-card table-card">
        <div className="card-header table-card-header">
          <div className="card-title">
            <TableIcon size={14} className="text-accent" />
            <span className="title-bold">{card.title}</span>
            <span className="card-time">{card.time}</span>
          </div>
          <div className="card-actions">
            <CopyButton text={card.rawText} />
          </div>
        </div>
        <div className="card-body table-card-body">
          <div className="data-table-viewport">
            <table className="native-log-table">
              <thead>
                <tr>
                  {card.headers.map((h, i) => (
                    <th key={i} style={{ textAlign: colAlignments[i] }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {card.rows.map((row, rIdx) => (
                  <tr key={rIdx}>
                    {row.map((cell, cIdx) => (
                      <td key={cIdx} style={{ textAlign: colAlignments[cIdx] }}>
                        {renderTableCell(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    )
  },
  (prev, next) => prev.card === next.card
)

/** LLM 分析报告卡片：Markdown 渲染报告正文，徽章显示模型名。 */
const LlmReportCard = memo(
  function LlmReportCard({ card }: { card: Extract<CardItem, { type: 'llm_report' }> }) {
    return (
      <div className="log-card llm-card">
        <div className="card-header llm-header">
          <div className="card-title">
            <Sparkles size={16} className="text-llm" />
            <span className="title-bold">AI 错误智能分析诊断报告</span>
            <span className="badge-pill llm-model">{card.model}</span>
            <span className="card-time">{card.time}</span>
          </div>
          <div className="card-actions">
            <CopyButton text={card.content} label="复制报告" />
          </div>
        </div>
        <div className="card-body">
          <LazyMarkdown content={card.content} className="llm-markdown-view" />
        </div>
      </div>
    )
  },
  (prev, next) => prev.card === next.card
)

/** 矩阵切片卡片：局部视野/雷达扫描的两字符单元格矩阵。 */
const MatrixGridCard = memo(
  function MatrixGridCard({ card }: { card: Extract<CardItem, { type: 'matrix_grid' }> }) {
    const [open, setOpen] = useState(true)

    return (
      <div className="log-card matrix-card">
        <div className="card-header" onClick={() => setOpen(!open)}>
          <div className="card-title">
            <MapIcon size={15} className="text-secondary" />
            <span className="title-bold">{card.title}</span>
            <span className="card-time">{card.time}</span>
          </div>
          <div className="card-actions">
            <CopyButton text={card.rawText} />
            <button className="card-btn-icon" aria-label="展开或折叠">
              {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
          </div>
        </div>
        {open && (
          <div className="card-body">
            <div className="map-grid-viewport">
              <div className="matrix-grid-rows">
                {card.rows.map((row, rIdx) => (
                  <div key={rIdx} className="matrix-row">
                    {row.map((cell, cIdx) => {
                      const meta = getCellMeta(cell)
                      return (
                        <span key={cIdx} className={`map-badge ${meta.cls}`} title={meta.label}>
                          {renderCellContent(cell)}
                        </span>
                      )
                    })}
                  </div>
                ))}
              </div>
            </div>

            <div className="map-legend-bar">
              <span className="legend-item"><Ship size={12} className="legend-icon text-fleet" /> 旗舰 (FL)</span>
              <span className="legend-item"><Crown size={12} className="legend-icon text-boss" /> Boss (BO)</span>
              <span className="legend-item"><Swords size={12} className="legend-icon text-enemy" /> 敌舰 (1M/EN)</span>
              <span className="legend-item"><Package size={12} className="legend-icon text-mystery" /> 物资/箱 (MY/RE)</span>
              <span className="legend-item"><PawPrint size={12} className="legend-icon text-meowfficer" /> 指挥喵 (ME)</span>
              <span className="legend-item"><AlertCircle size={12} className="legend-icon text-event" /> 事件 (EX)</span>
              <span className="legend-item"><Radar size={12} className="legend-icon text-device" /> 装置 (SD)</span>
              <span className="legend-item"><Ban size={12} className="legend-icon text-impassable" /> 不可走 (++)</span>
              <span className="legend-item"><span className="legend-dot dot-sea" /> 海域 (--)</span>
            </div>
          </div>
        )}
      </div>
    )
  },
  (prev, next) => prev.card === next.card
)

function interpolateColor(
  c1: [number, number, number],
  c2: [number, number, number],
  factor: number
): string {
  const r = Math.round(c1[0] + factor * (c2[0] - c1[0]))
  const g = Math.round(c1[1] + factor * (c2[1] - c1[1]))
  const b = Math.round(c1[2] + factor * (c2[2] - c1[2]))
  return `rgb(${r}, ${g}, ${b})`
}

/** 热力渐变停靠点：t ∈ [0,1] 由代价值归一而来，按远近插值取色。 */
const HEATMAP_STOPS: [number, [number, number, number]][] = [
  [0.0, [2, 132, 199]],   // #0284c7 Sky Blue（近距代价 1）
  [0.25, [37, 99, 235]],  // #2563eb 蓝色调
  [0.5, [124, 58, 237]],  // #7c3aed 紫色调
  [0.75, [192, 38, 211]], // #c026d3 品红色调
  [1.0, [225, 29, 72]],   // #e11d48 Rose（远距最高代价）
]

/** 代价格子的配色：0 是起点绿，≥9000 是不可达暗格，其余按 maxCost 归一到渐变色带。 */
function getCostHeatmapStyle(num: number, maxCost: number): CSSProperties {
  if (num >= 9000) {
    return {
      backgroundColor: '#000000',
      color: '#52525b',
      fontSize: '10px',
    }
  }
  if (num === 0) {
    return {
      backgroundColor: '#10b981',
      color: '#ffffff',
      fontWeight: 700,
    }
  }
  const t = Math.max(0, Math.min(1, maxCost > 1 ? (num - 1) / (maxCost - 1) : 0))
  for (let i = 0; i < HEATMAP_STOPS.length - 1; i++) {
    const previousStop = HEATMAP_STOPS[i]
    const nextStop = HEATMAP_STOPS[i + 1]
    if (!previousStop || !nextStop) continue
    const [t1, c1] = previousStop
    const [t2, c2] = nextStop
    if (t >= t1 && t <= t2 && t2 !== t1) {
      const factor = (t - t1) / (t2 - t1)
      return {
        backgroundColor: interpolateColor(c1, c2, factor),
        color: '#ffffff',
      }
    }
  }
  return {
    backgroundColor: '#0284c7',
    color: '#ffffff',
  }
}

/** 寻路代价热力图卡片：代价格子按 HEATMAP_STOPS 渐变着色，附图例。 */
const CostGridCard = memo(
  function CostGridCard({ card }: { card: Extract<CardItem, { type: 'cost_grid' }> }) {
    const [open, setOpen] = useState(true)
    const shapeStr = `${card.cols.length}×${card.rows.length}`

    const maxCost = useMemo(() => {
      let max = 1
      for (const row of card.rows) {
        for (const val of row.values) {
          const n = parseInt(val, 10)
          if (!isNaN(n) && n < 9000 && n > max) {
            max = n
          }
        }
      }
      return max
    }, [card.rows])

    return (
      <div className="log-card cost-card">
        <div className="card-header" onClick={() => setOpen(!open)}>
          <div className="card-title">
            <Compass size={15} className="text-accent" />
            <span className="title-bold">寻路移动代价热力图 (Cost Map)</span>
            <span className="badge-shape">{shapeStr}</span>
            <span className="card-time">{card.time}</span>
          </div>
          <div className="card-actions">
            <CopyButton text={card.rawText} label="复制矩阵" />
            <button className="card-btn-icon" aria-label="展开或折叠">
              {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
          </div>
        </div>
        {open && (
          <div className="card-body">
            <div className="map-grid-viewport">
              <table className="map-ascii-table cost-table">
                <thead>
                  <tr>
                    <th className="map-th-corner">#</th>
                    {card.cols.map((col, idx) => (
                      <th key={idx} className="map-th-col">{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {card.rows.map((row) => (
                    <tr key={row.rowNum}>
                      <td className="map-td-row">{row.rowNum}</td>
                      {row.values.map((val, cIdx) => {
                        const num = parseInt(val, 10)
                        const isObstacle = num >= 9000
                        const isOrigin = num === 0
                        const cellStyle = getCostHeatmapStyle(num, maxCost)
                        const title = isObstacle
                          ? '不可达障碍 (9999)'
                          : isOrigin
                          ? '寻路起点 (0 步)'
                          : `移动代价: ${num} 步`

                        return (
                          <td key={cIdx} className="map-td-cell">
                            <span
                              className={`cost-cell ${isObstacle ? 'cost-wall' : isOrigin ? 'cost-origin' : 'cost-path'}`}
                              style={cellStyle}
                              title={title}
                            >
                              {val}
                            </span>
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="map-legend-bar">
              <span className="legend-item"><span className="legend-dot dot-origin" /> 起点 (0)</span>
              <span className="legend-item"><span className="legend-dot dot-cost-low" /> 近距/低代价</span>
              <span className="legend-item"><span className="legend-dot dot-cost-mid" /> 中距代价</span>
              <span className="legend-item"><span className="legend-dot dot-cost-high" /> 远距代价 (最高: {maxCost})</span>
              <span className="legend-item"><span className="legend-dot dot-cost-wall" /> 不可达障碍 (9999)</span>
            </div>
          </div>
        )}
      </div>
    )
  },
  (prev, next) => prev.card === next.card
)

/** 系统横幅卡片：双横线夹标题的全宽横幅。 */
const SystemBannerCard = memo(
  function SystemBannerCard({ card }: { card: Extract<CardItem, { type: 'system_banner' }> }) {
    return (
      <div className="log-card system-banner-card">
        <div className="banner-double-rule" />
        <div className="banner-title-text">{card.title}</div>
        <div className="banner-double-rule" />
      </div>
    )
  },
  (prev, next) => prev.card === next.card
)

/** 任务阶段标题卡片：横线夹标题，level 区分主/次。 */
const StageHeaderCard = memo(
  function StageHeaderCard({ card }: { card: Extract<CardItem, { type: 'stage_header' }> }) {
    return (
      <div className={`log-card stage-header-card level-${card.level}`}>
        <div className="stage-rule-bar" />
        <div className="stage-title-wrap">
          <span className="stage-title">{card.title}</span>
          {card.time && <span className="stage-time">{card.time}</span>}
        </div>
        <div className="stage-rule-bar" />
      </div>
    )
  },
  (prev, next) => prev.card === next.card
)

/** 常规单行日志行：级别、时间与正文的高亮渲染。 */
const SingleLogLineCard = memo(
  function SingleLogLineCard({ card, search }: { card: Extract<CardItem, { type: 'single' }>; search: string }) {
    const lvlKey = card.level.toLowerCase()
    return (
      <div className={`log-line log-entry-line level-${lvlKey} log-card-line`}>
        <span className={`log-lvl lvl-${lvlKey}`}>{card.level}</span>
        <span className="log-ts">{card.time}</span>
        <span className="log-divider">│</span>
        <span className="log-msg">{renderTokens(card.message, search)}</span>
      </div>
    )
  },
  (prev, next) => prev.card === next.card && prev.search === next.search
)

export {
  PerspectiveCard,
  PropertySheetCard,
  renderTableCell,
  DataTableCard,
  LlmReportCard,
  MatrixGridCard,
  interpolateColor,
  HEATMAP_STOPS,
  getCostHeatmapStyle,
  CostGridCard,
  SystemBannerCard,
  StageHeaderCard,
  SingleLogLineCard,
}
