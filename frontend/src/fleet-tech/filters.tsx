import type {Dispatch, SetStateAction} from 'react'
import {Button} from '../components/ui/button'

export const fleetShipTypes = [1, 2, 3, 18, 4, 5, 7, 6, 13, 12, 10, 8, 17, 19, 22]
export const fleetAttributes = [1, 2, 3, 4, 5, 6, 9, 8, 12]
export const fleetRarities = ['N', 'R', 'SR', 'SSR', 'UR', 'PR', 'DR']
// Ledger identities use catalog names and distinguish guided-missile destroyers.
export const ledgerShipTypes = ['驱逐', '轻巡', '重巡', '超巡', '战巡', '战列', '正航', '轻航', '重炮', '维修', '航战', '潜艇', '潜母', '运输', '导驱', '风帆']
export const ledgerTypeIds: Record<string, number> = {'驱逐': 1, '轻巡': 2, '重巡': 3, '超巡': 18, '战巡': 4, '战列': 5, '正航': 7, '轻航': 6, '重炮': 13, '维修': 12, '航战': 10, '潜艇': 8, '潜母': 17, '运输': 19, '导驱': 1, '风帆': 22}
export type FleetFilters = Record<string, string[]>

export function FleetFilterRow({filter, label, options, filters, setFilters, all}: {
  filter: string; label: string; options: [string, string][]; filters: FleetFilters
  setFilters: Dispatch<SetStateAction<FleetFilters>>; all: string
}) {
  return <div className="ft-filter-row"><strong>{label}</strong><div className="ft-chips">{[['', all], ...options].map(([value, text]) => {
    const selected = value ? filters[filter]?.includes(value) ?? false : !filters[filter]?.length
    return <Button type="button" size="sm" variant={selected ? 'default' : 'outline'} key={value} aria-pressed={selected} onClick={() => setFilters(current => ({...current, [filter]: value ? current[filter]?.includes(value) ? current[filter]!.filter(item => item !== value) : [...current[filter] ?? [], value] : []}))}>{text}</Button>
  })}</div></div>
}
