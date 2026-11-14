/**
 * 从 LogCardView.tsx 原 823-1079 行提取，纯搬迁未改动。
 * 海图格子语义识别与地图网格卡片渲染。
 */

import {
  memo,
  useState,
  type ReactNode,
} from 'react'
import {
  AlertCircle,
  Anchor,
  Ban,
  BookOpen,
  ChevronDown,
  ChevronRight,
  Crown,
  Crosshair,
  HelpCircle,
  Map as MapIcon,
  Package,
  PawPrint,
  Radar,
  Ship,
  Skull,
  Swords,
  Zap,
} from 'lucide-react'
import type { CardItem } from './aggregate'
import { CopyButton } from './shared'

// 语义色彩与 Tooltip 释义词典

const CELL_DICT: Record<string, { label: string; cls: string }> = {
  '++': { label: '陆地/不可通航', cls: 'cell-land' },
  '--': { label: '海洋/安全航道', cls: 'cell-sea' },
  '..': { label: '视野盲区/未检测', cls: 'cell-blind' },
  '==': { label: '已清除/已扫描', cls: 'cell-cleared' },
  'FL': { label: '第一舰队旗舰 (当前控制)', cls: 'cell-fleet-1' },
  'Fl': { label: '第二舰队', cls: 'cell-fleet-2' },
  'ss': { label: '潜艇部队', cls: 'cell-submarine' },
  'BO': { label: '关卡旗舰 Boss', cls: 'cell-boss' },
  'MY': { label: '神秘问号调查点', cls: 'cell-mystery' },
  'AM': { label: '弹药补给点', cls: 'cell-ammo' },
  'FR': { label: '机械要塞', cls: 'cell-fortress' },
  'MI': { label: '导弹支援点', cls: 'cell-missile' },
  'Fc': { label: '被塞壬捕获 (移动受限)', cls: 'cell-caught' },
  'SU': { label: '塞壬精英敌人', cls: 'cell-siren' },
  'AK': { label: '明石隐藏商店', cls: 'cell-akashi' },
  'AL': { label: '护送盟友货船', cls: 'cell-ally' },
  'RE': { label: '大世界资源箱', cls: 'cell-resource' },
  'EX': { label: '大世界感叹号特殊事件', cls: 'cell-event' },
  'ME': { label: '大世界指挥喵搜索点', cls: 'cell-meowfficer' },
  'QU': { label: '神秘问号事件', cls: 'cell-question' },
  'SD': { label: '大世界环境扫描装置', cls: 'cell-device' },
  'AR': { label: '大世界机密档案记录', cls: 'cell-archive' },
  'PO': { label: '大世界补给港口', cls: 'cell-port' },
  'EN': { label: '敌方舰队', cls: 'cell-enemy' },
}

function getCellMeta(code: string): { label: string; cls: string } {
  if (CELL_DICT[code]) return CELL_DICT[code]
  if (/^[0-3][LMCET]/.test(code)) {
    const star = code[0]
    const genreMap: Record<string, string> = { L: '轻型巡逻', M: '主力战列', C: '航空航母', E: '未知敌舰', T: '运输舰队' }
    const genre = genreMap[code[1]] || '敌舰'
    return { label: `${star}★ ${genre}敌舰`, cls: 'cell-enemy' }
  }
  return { label: `未知标记 (${code})`, cls: 'cell-default' }
}

function renderCellContent(code: string): ReactNode {
  // 1. 敌舰：行首 0-3 星数 + 舰种字母（1M、2C、3E…），EN 也是敌舰。
  if (/^[0-3][LMCET]/.test(code) || code === 'EN') {
    const star = code[0]
    return (
      <span className="cell-icon-wrap" title={`${star === 'E' ? '' : star + '★ '}敌舰 (${code})`}>
        <Swords size={13} className="cell-icon" />
        {star !== '0' && star !== 'E' && <span className="cell-sub-star">{star}</span>}
      </span>
    )
  }
  if (code === 'SU') {
    return (
      <span className="cell-icon-wrap" title="塞壬精英敌人 (SU)">
        <Skull size={13} className="cell-icon" />
      </span>
    )
  }

  if (code === 'BO') {
    return (
      <span className="cell-icon-wrap" title="关卡旗舰 Boss (BO)">
        <Crown size={14} className="cell-icon" />
      </span>
    )
  }

  if (code === 'FL' || code === 'Fl') {
    return (
      <span className="cell-icon-wrap" title="主力舰队旗舰 (FL)">
        <Ship size={13} className="cell-icon" />
      </span>
    )
  }
  if (code === 'ss') {
    return (
      <span className="cell-icon-wrap" title="潜艇部队 (ss)">
        <Anchor size={13} className="cell-icon" />
      </span>
    )
  }

  if (code === '++') {
    return (
      <span className="cell-icon-wrap" title="不可通航陆地/障碍 (++)">
        <Ban size={12} className="cell-icon" />
      </span>
    )
  }
  if (code === 'Fc') {
    return (
      <span className="cell-icon-wrap" title="被塞壬捕获/移动受限 (Fc)">
        <Ban size={12} className="cell-icon" />
      </span>
    )
  }
  if (code === 'FR') {
    return (
      <span className="cell-icon-wrap" title="机械要塞不可走 (FR)">
        <Ban size={12} className="cell-icon" />
      </span>
    )
  }

  // 5. 海域与已扫格（--、==）不画图标，只留 getCellMeta 给的底色。
  if (code === '--' || code === '==') {
    return null
  }

  if (code === 'ME') {
    return (
      <span className="cell-icon-wrap" title="大世界指挥喵搜索点 (ME)">
        <PawPrint size={13} className="cell-icon" />
      </span>
    )
  }
  if (code === 'EX') {
    return (
      <span className="cell-icon-wrap" title="大世界感叹号特殊事件 (EX)">
        <AlertCircle size={13} className="cell-icon" />
      </span>
    )
  }
  if (code === 'SD') {
    return (
      <span className="cell-icon-wrap" title="大世界环境扫描探测装置 (SD)">
        <Radar size={13} className="cell-icon" />
      </span>
    )
  }
  if (code === 'AR') {
    return (
      <span className="cell-icon-wrap" title="大世界机密档案记录 (AR)">
        <BookOpen size={13} className="cell-icon" />
      </span>
    )
  }
  if (code === 'PO') {
    return (
      <span className="cell-icon-wrap" title="大世界补给港口 (PO)">
        <Anchor size={13} className="cell-icon" />
      </span>
    )
  }

  if (code === 'MY' || code === 'QU') {
    return (
      <span className="cell-icon-wrap" title="神秘问号调查点 (MY/QU)">
        <HelpCircle size={13} className="cell-icon" />
      </span>
    )
  }
  if (code === 'RE' || code === 'AK') {
    return (
      <span className="cell-icon-wrap" title="物资资源箱/明石商店 (RE/AK)">
        <Package size={13} className="cell-icon" />
      </span>
    )
  }
  if (code === 'AM' || code === 'MA') {
    return (
      <span className="cell-icon-wrap" title="弹药补给点 (AM)">
        <Zap size={13} className="cell-icon" />
      </span>
    )
  }
  if (code === 'MI') {
    return (
      <span className="cell-icon-wrap" title="导弹支援点 (MI)">
        <Crosshair size={13} className="cell-icon" />
      </span>
    )
  }

  if (code === '..') {
    return <span className="cell-blind-dots">··</span>
  }

  return <span>{code}</span>
}

// 专用卡片组件集

/** 全局海图网格卡片：列头 + 行号表格，格子按 CELL_DICT 语义着色，附图例。 */
const MapGridCard = memo(
  function MapGridCard({ card }: { card: Extract<CardItem, { type: 'map_grid' }> }) {
    const [expanded, setExpanded] = useState(true)
    const shapeStr = `${card.cols.length}×${card.rows.length}`

    return (
      <div className="log-card map-card">
        <div className="card-header" onClick={() => setExpanded(!expanded)}>
          <div className="card-title">
            <MapIcon size={16} className="text-accent" />
            <span className="title-bold">海域战术地图快照</span>
            <span className="badge-shape">{shapeStr}</span>
            <span className="card-time">{card.time}</span>
          </div>
          <div className="card-actions">
            <CopyButton text={card.rawText} label="复制矩阵" />
            <button className="card-btn-icon" aria-label="展开或折叠">
              {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
          </div>
        </div>

        {expanded && (
          <div className="card-body">
            <div className="map-grid-viewport">
              <table className="map-ascii-table">
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
                      {row.cells.map((cell, cIdx) => {
                        const meta = getCellMeta(cell)
                        return (
                          <td key={cIdx} className="map-td-cell">
                            <span
                              className={`map-badge ${meta.cls}`}
                              title={`[${card.cols[cIdx]}${row.rowNum}] ${meta.label}`}
                            >
                              {renderCellContent(cell)}
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

export {
  CELL_DICT,
  getCellMeta,
  renderCellContent,
  MapGridCard,
}
