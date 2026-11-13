/**
 * @fileoverview 统计页多页面组合链槽位编辑组件。
 */

import { Plus, X } from 'lucide-react'

import { useApp } from '../app/context'
import type { PageId } from '../app/statisticsLayout'
import { Button } from './ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './official-ui/select'

/** 页面组合的槽位区：一行一条链，行尾是待填入的空槽位；行内不足两页时不参与组合。 */
export function PageChainSlots({rows, labels, options, onPlace, onRemove}: {
  rows: PageId[][]
  labels: Record<string, string>
  options: PageId[]
  onPlace: (rowIndex: number, page: PageId) => void
  onRemove: (page: PageId) => void
}) {
  const {ui} = useApp()
  const addSlot = (rowIndex: number) => <span className="statistics-chain-slot">
    <Select value="" disabled={!options.length} onValueChange={page => onPlace(rowIndex, page as PageId)}>
      <SelectTrigger aria-label={ui('stats.chainAdd')} title={ui('stats.chainAdd')}><Plus/><SelectValue placeholder={ui('stats.chainPick')}/></SelectTrigger>
      <SelectContent>{options.map(page => <SelectItem value={page} key={page}>{labels[page]}</SelectItem>)}</SelectContent>
    </Select>
  </span>

  const lastFull = rows.length === 0 || rows[rows.length - 1].length >= 2

  return <div className="statistics-chain-slots" aria-label={ui('stats.chainTitle')}>
    {rows.map((row, rowIndex) => <div className="statistics-chain-row" key={row[0]}>
      {row.map(page => <span className="statistics-chain-card" key={page}>
        <span className="statistics-chain-label">{labels[page]}</span>
        <Button type="button" variant="ghost" size="icon-xs" aria-label={ui('stats.chainRemove')} title={ui('stats.chainRemove')} onClick={() => onRemove(page)}><X/></Button>
      </span>).flatMap((card, index) => index === 0 ? [card] : [<span className="statistics-chain-link" aria-hidden="true" key={'link' + index}/>, card])}
      {row.length > 0 ? <span className="statistics-chain-link" aria-hidden="true"/> : null}
      {addSlot(rowIndex)}
    </div>)}
    {/* 行号取 -1 表示新开一条链：父级 placeInSlot 对负数行号追加新行 */}
    {lastFull ? <div className="statistics-chain-row">{addSlot(-1)}</div> : null}
  </div>
}
