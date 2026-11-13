/**
 * @fileoverview 资源流水桑基图的数据构造：把 ResourceFlowReport 折算成 ECharts 的节点与连线。
 */
import type {ResourceFlowReport} from '../api/types'

/** 桑基图节点：资源居中层（depth 1），来源节点（depth 0）流入、去向节点（depth 2）流出。 */
export interface FlowNode {name: string; label: string; depth: number; amount?: number; resource?: string; task?: string; itemStyle?: {color: string}}
/** 桑基图连线：value 是占该资源总量（进出较大者）的百分比，amount 是绝对数量。 */
export interface FlowLink {source: string; target: string; value: number; amount: number; label: string; resource: string}
/** 单资源保持数量比例，多资源分别归一化；补足库存支出或区间结余以守恒。 */
export function flowGraph(report: ResourceFlowReport, labels: {resource: (key: string) => string; task: (key: string) => string; stock: string; balance: string}) {
  const nodes: FlowNode[] = [], links: FlowLink[] = []
  const keys = [...new Set(report.flows.map(row => row.resource))]
  keys.forEach((resource, index) => {
    const rows = report.flows.filter(row => row.resource === resource)
    const income = rows.reduce((sum, row) => sum + row.income, 0), expense = rows.reduce((sum, row) => sum + row.expense, 0)
    const total = Math.max(income, expense)
    if (!total) return
    const color = ['#549ad0', '#d6a653', '#77ab80', '#ad85c5', '#d48078', '#69adb3'][index % 6]
    const center = `resource:${resource}`
    nodes.push({name: center, label: labels.resource(resource), depth: 1, resource, itemStyle: {color}})
    const add = (id: string, label: string, amount: number, incoming: boolean, task?: string) => {
      nodes.push({name: id, label, amount, depth: incoming ? 0 : 2, task, resource, itemStyle: {color: task === 'Unattributed' ? '#9299a1' : color}})
      links.push({source: incoming ? id : center, target: incoming ? center : id, value: amount / total * 100, amount, label, resource})
    }
    const grouped = new Map<string, {income: number; expense: number}>()
    rows.forEach(row => {const value = grouped.get(row.task) ?? {income: 0, expense: 0}; value.income += row.income; value.expense += row.expense; grouped.set(row.task, value)})
    grouped.forEach((value, task) => {
      if (value.income) add(`income:${resource}:${task}`, labels.task(task), value.income, true, task)
      if (value.expense) add(`expense:${resource}:${task}`, labels.task(task), value.expense, false, task)
    })
    if (expense > income) add(`stock:${resource}`, labels.stock, expense - income, true)
    if (income > expense) add(`balance:${resource}`, labels.balance, income - expense, false)
  })
  return {nodes, links}
}
