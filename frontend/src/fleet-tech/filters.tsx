/**
 * @fileoverview 舰队相关页面的筛选行组件与舰种/属性/稀有度清单。
 */

import type {Dispatch, SetStateAction} from 'react'
import {Button} from '../components/ui/button'

/** 舰队科技与心智计算共用的舰种类型 ID，顺序即筛选 chip 的展示顺序。 */
export const fleetShipTypes = [1, 2, 3, 18, 4, 5, 7, 6, 13, 12, 10, 8, 17, 19, 22]
/** 舰船属性 ID，顺序即筛选 chip 的展示顺序。 */
export const fleetAttributes = [1, 2, 3, 4, 5, 6, 9, 8, 12]
/** 舰船稀有度档位；船坞台账只用前五档（N–UR）。 */
export const fleetRarities = ['N', 'R', 'SR', 'SSR', 'UR', 'PR', 'DR']
/** 台账舰船身份用图鉴名称区分：导驱与驱逐同为类型 1，按数字 ID 分不出来，所以按名称另维护一份。 */
export const ledgerShipTypes = ['驱逐', '轻巡', '重巡', '超巡', '战巡', '战列', '正航', '轻航', '重炮', '维修', '航战', '潜艇', '潜母', '运输', '导驱', '风帆']
/** 舰种名称 → 图鉴类型 ID；导驱与驱逐共用 1，身份靠名称区分。 */
export const ledgerTypeIds: Record<string, number> = {'驱逐': 1, '轻巡': 2, '重巡': 3, '超巡': 18, '战巡': 4, '战列': 5, '正航': 7, '轻航': 6, '重炮': 13, '维修': 12, '航战': 10, '潜艇': 8, '潜母': 17, '运输': 19, '导驱': 1, '风帆': 22}
type FleetFilters = Record<string, string[]>

/**
 * 单组筛选行：首枚 chip 是「全部」（value 为空串，选中即清空该组），其余 chip 多选切换。
 * 选中态完全由 filters[filter] 推导，组件自身不保存状态。
 *
 * @param options 可选项 [值, 显示文案] 列表，顺序即 chip 排列顺序。
 * @param all 「全部」chip 的显示文案。
 */
export function FleetFilterRow({filter, label, options, filters, setFilters, all}: {
  filter: string; label: string; options: [string, string][]; filters: FleetFilters
  setFilters: Dispatch<SetStateAction<FleetFilters>>; all: string
}) {
  return <div className="ft-filter-row"><strong>{label}</strong><div className="ft-chips">{[['', all], ...options].map(([value, text]) => {
    const selected = value ? filters[filter]?.includes(value) ?? false : !filters[filter]?.length
    return <Button type="button" size="sm" variant={selected ? 'default' : 'outline'} key={value} aria-pressed={selected} onClick={() => setFilters(current => ({...current, [filter]: value ? current[filter]?.includes(value) ? current[filter]!.filter(item => item !== value) : [...current[filter] ?? [], value] : []}))}>{text}</Button>
  })}</div></div>
}
