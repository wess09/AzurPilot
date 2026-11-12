/**
 * @fileoverview 统计数据明细与掉落记录表格组件。
 */

import type {ReactNode} from 'react'
import { ArrowDown, ArrowUp, Search } from 'lucide-react'
import { useState } from 'react'
import type { StatTable, TableSort } from '../api/types'
import { downloadCsv } from './statisticsData'
import { DEFAULT_TABLE_ROWS } from '../app/statisticsLayout'
import { useApp } from '../app/context'
import { localeForLanguage } from '../i18n'
import { withTranslatedKeys } from './statisticsText'
import { Input } from './official-ui/input'
import { Button } from './ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table'

const iconBase = import.meta.env.BASE_URL
// 键为中文名；withTranslatedKeys 补上译名，翻译后的列名、物品名仍能找到图标。
export const resourceIcons: Record<string, string> = withTranslatedKeys({
  '钻石': `${iconBase}diamond.webp`,
  '心智魔方': `${iconBase}cube.webp`,
  '魔方': `${iconBase}cube.webp`,
  '心智单元': `${iconBase}cognitive_chips.webp`,
  '石油': `${iconBase}oil.webp`,
  '物资': `${iconBase}gold.webp`,
  '完成委托': `${iconBase}honor_medal.webp`,
  '活动 PT': `${iconBase}pt.webp`,
  '行动力': `${iconBase}guild_coin.webp`,
  '作战补给凭证': `${iconBase}supply_token.webp`,
  '特别兑换凭证': `${iconBase}special_token.webp`,
  '核心数据': `${iconBase}core_data.webp`,
  '荣誉勋章': `${iconBase}honor_medal.webp`,
  '功勋': `${iconBase}merit.webp`,
  '舰队币': `${iconBase}stamina.webp`,
})

// 科研掉落用仓库里的模板图当图标，后端把 /research-items 挂到 assets/stats/research_items，
// 不走前端构建，补了新模板立刻生效。单元格值形如 'research:BlueprintValparaiso'。
const RESEARCH_PREFIX = 'research:'
// 大世界掉落同理，值形如 'opsi:PlateGeneralT4'，后端把 /opsi-items 挂到
// assets/stats/opsi_reward_items，缺失时回退到 opsi_items 中的同名领奖模板。
const OPSI_PREFIX = 'opsi:'
const STORAGE_PREFIX = 'storage:'
/** 带模板图标的单元格值前缀全集；判断一行是否模板行时用它。 */
export const TEMPLATE_PREFIXES = [RESEARCH_PREFIX, OPSI_PREFIX, STORAGE_PREFIX]

/**
 * 把单元格值解析成图标：模板前缀（storage:/research:/opsi:）走对应模板目录，否则按资源名查 resourceIcons。
 * 返回 undefined 表示该值没有图标可显示。
 * @param resources false 时跳过资源名查找，用于已套模板图的行——部分科研物品名与资源名相同，会被误套资源图标。
 */
export function resolveIcon(value: string, resources = true): {src: string, label: string} | undefined {
  if (value.startsWith(STORAGE_PREFIX)) {
    return {src: `${iconBase}storage-items/${value.slice(STORAGE_PREFIX.length)}.png`, label: ''}
  }
  if (value.startsWith(RESEARCH_PREFIX)) {
    const name = value.slice(RESEARCH_PREFIX.length)
    // 图标列不重复显示模板名：它很长（Prototype_Quadruple_610mm_Cruiser_...）会把列撑爆，
    // 而中文名在「物品」列已经有了；搜索也走那一列。
    return {src: `${iconBase}research-items/${name}.png`, label: ''}
  }
  if (value.startsWith(OPSI_PREFIX)) {
    const name = value.slice(OPSI_PREFIX.length)
    return {src: `${iconBase}opsi-items/${name}.png`, label: ''}
  }
  // resources=false：这一行已经有科研模板图标了，「物品」列别再按资源名查一次——
  // 「心智单元」「物资」既是科研物品名又是资源名，会被套上资源图标（还可能是错的那张）。
  if (!resources) return undefined
  const icon = resourceIcons[value]
  return icon ? {src: icon, label: value} : undefined
}

/** 统计表格卡片：搜索、排序、分页与 CSV 导出齐全；plain 模式把每个数据行压成一行文字。 */
export function StatisticsTable({data, foldControl, editControls, rows: rowsPerPage = DEFAULT_TABLE_ROWS, icons = false, plain = false}: {
  data: StatTable
  foldControl?: ReactNode
  /** 编辑模式下的表格设置控件，与其他卡片动作同排。 */
  editControls?: ReactNode
  /** 每页行数，0 表示不分页。 */
  rows?: number
  /** 为纯数值补上所在列的资源图标。 */
  icons?: boolean
  /** 简洁显示：不显示表头，每个数据行压成一行文字。 */
  plain?: boolean
}) {
  const {ui, language} = useApp()
  const [page, setPage] = useState(0)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<TableSort>()
  const activeSort = sort ?? data.defaultSort
  const rows = data.rows.filter(row => row.some(value => String(value ?? '').toLowerCase().includes(search.toLowerCase())))
  if (activeSort) rows.sort((a, b) => {
    const av = a[activeSort.index], bv = b[activeSort.index]
    const order = typeof av === 'number' && typeof bv === 'number' ? av - bv : String(av ?? '').localeCompare(String(bv ?? ''), localeForLanguage(language), {numeric: true})
    return order * (activeSort.descending ? -1 : 1)
  })
// 接口会把数值当字符串发回来（'98'、'5,122'），补图标时两种都要当成数值。
function numericValue(value: StatTable['rows'][number][number]): number | undefined {
  if (typeof value === 'number') return value
  if (typeof value !== 'string' || !value.trim()) return undefined
  const parsed = Number(value.replace(/,/g, ''))
  return Number.isFinite(parsed) ? parsed : undefined
}

  // 单元格显示文本：图标值取图标自带的标签，数字按语言格式化，空值给破折号。
  const cellText = (value: StatTable['rows'][number][number], icon?: {src: string; label: string}) => icon ? icon.label : value == null ? '—' : typeof value === 'number' ? value.toLocaleString(localeForLanguage(language), {maximumFractionDigits: 4}) : String(value)
  const perPage = rowsPerPage > 0 ? rowsPerPage : Math.max(rows.length, 1)
  const pages = Math.max(1, Math.ceil(rows.length / perPage))
  const current = Math.min(page, pages - 1)
  const singleRow = rows.length === 1
  // 只有一页时不画分页栏：页码恒为 1 / 1，两个翻页钮也点不动。
  return <section className={`statistics-table${singleRow ? ' is-single-row' : ''}`}><div className="panel-heading"><h3>{data.title}</h3><div className="table-search"><Search size={14}/><Input className="w-full min-w-30 max-w-60" aria-label={ui('stats.searchTable', {title: data.title})} value={search} onChange={event => {setSearch(event.target.value); setPage(0)}} placeholder={ui('stats.searchPlaceholder')}/><span>{ui('stats.records', {count: rows.length})}</span></div><div className="stat-card-actions">{editControls}{foldControl}<Button variant="ghost" size="sm" disabled={!rows.length} onClick={() => downloadCsv(data.title, [data.columns, ...rows])}>{ui('stats.exportDetails')}</Button></div></div>{data.note && <p className="panel-note">{data.note}</p>}<div className="table-scroll">{plain ? (<div className="table-lines">{rows.slice(current * perPage, (current + 1) * perPage).map((row, index) => (
              <p className="table-line" key={index}>
                <span className="table-line-first">{cellText(row[0])}：</span>
                {row.slice(1).map((value, cell) => {const icon = typeof value === 'string' ? resolveIcon(value, false) : undefined
                  const src = icon?.src ?? (numericValue(value) !== undefined ? resourceIcons[data.columns[cell + 1]] : undefined)
                  return ({src, text: cellText(value, icon)})}).filter(item => item.src && item.text !== '—').map((item, cell) => (
                  <span className="table-line-cell" key={cell}>{cell ? '、' : ''}{item.src ? <img className="table-resource-icon" src={item.src} alt="" draggable={false}/> : null}{item.src ? '×' : ''}{item.text}</span>))}
      </p>))}</div>) : (<Table className="min-w-full whitespace-nowrap"><TableHeader className="sticky top-0 z-10"><TableRow>{data.columns.map((column, index) => {const colIcon = resourceIcons[column]; return <TableHead key={column} aria-sort={activeSort?.index === index ? activeSort.descending ? 'descending' : 'ascending' : 'none'}><Button type="button" variant="ghost" size="sm" onClick={() => {setPage(0); setSort(currentSort => {const current = currentSort ?? data.defaultSort; return {index, descending: current?.index === index ? !current.descending : false}})}}>{colIcon && <img className="table-resource-icon table-header-icon" src={colIcon} alt="" width={24} height={24} draggable={false}/>}{column}{activeSort?.index === index ? activeSort.descending ? <ArrowDown size={14} aria-hidden="true"/> : <ArrowUp size={14} aria-hidden="true"/> : null}</Button></TableHead>})}</TableRow></TableHeader><TableBody>{rows.slice(current * perPage, (current + 1) * perPage).map((row, index) => {const templateRow = row.some(value => typeof value === 'string' && TEMPLATE_PREFIXES.some(prefix => value.startsWith(prefix))); return <TableRow key={index}>{row.map((value, cell) => {const icon = typeof value === 'string' ? resolveIcon(value, !templateRow) : undefined; const formatted = cellText(value, icon); const columnIcon = numericValue(value) !== undefined && (icons || plain) ? resourceIcons[data.columns[cell]] : undefined; return <TableCell key={cell}>{icon ? <span className="table-resource-cell"><img className="table-resource-icon" src={icon.src} alt="" width={26} height={26} draggable={false}/><span>{formatted}</span></span> : columnIcon ? <span className="table-resource-cell"><img className="table-resource-icon" src={columnIcon} alt="" width={26} height={26} draggable={false}/><span>{formatted}</span></span> : formatted}</TableCell>})}</TableRow>})}</TableBody></Table>)}{!rows.length && <p className="panel-note">{ui('stats.noRecords')}</p>}</div>{pages > 1 && <div className="table-toolbar"><Button variant="ghost" size="sm" disabled={!current} onClick={() => setPage(current - 1)}>{ui('common.previous')}</Button><span>{current + 1} / {pages}</span><Button variant="ghost" size="sm" disabled={current + 1 === pages} onClick={() => setPage(current + 1)}>{ui('common.next')}</Button></div>}</section>
}
