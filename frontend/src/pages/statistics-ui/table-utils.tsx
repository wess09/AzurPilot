/**
 * @fileoverview 明细表相关的纯助手：图标判定、指标摊表与行数输入控件。
 *
 * 从 Statistics.tsx 拆分而来。
 */
import {useDraftInput} from '../../components/FormControls'
import {resourceIcons, TEMPLATE_PREFIXES} from '../../components/StatisticsTable'
import {Input} from '../../components/official-ui/input'
import type { StatTable, StatisticsReport } from '../../api/types'

/**
 * 数字草稿输入框：失焦或回车提交非负整数，输入过程不触发 onCommit。
 *
 * @param value 当前值。
 * @param label 输入框的可访问名称。
 * @param onCommit 提交回调。
 */
export function NumberDraftInput({value, label, onCommit}: {value: number; label: string; onCommit: (value: number) => void}) {
  const draft = useDraftInput(String(value), text => {
    const parsed = Number(text)
    if (Number.isFinite(parsed) && parsed >= 0) onCommit(Math.floor(parsed))
  })
  return <Input type="number" min={0} aria-label={label} title={label} {...draft}/>
}

/**
 * 这张表有没有图标可出：资源名认列名；科研与大世界掉落的图标写在单元格值里（research: / opsi: 前缀），
 * 列名看不出来，两者都要查。
 *
 * @param table 待判定的统计表。
 * @returns 任一列或单元格带图标时为 true。
 */
export function hasTableIcons(table: StatTable): boolean {
  if (table.columns.some(column => column in resourceIcons || TEMPLATE_PREFIXES.some(prefix => column.startsWith(prefix)))) return true
  return table.rows.some(row => row.some(value => typeof value === 'string' && TEMPLATE_PREFIXES.some(prefix => value.startsWith(prefix))))
}

/**
 * 收获的表格模式：把指标摊成一张单行表，复用明细表那套表格。
 * 标题由调用方带前缀传入（如「大世界总结·收获」）。
 *
 * @param title 表标题。
 * @param metrics 收获指标列表。
 */
export function metricsTableData(title: string, metrics: StatisticsReport['metrics']): StatTable {
  return {title, columns: metrics.map(item => item.label), rows: [metrics.map(item => item.value)]}
}
