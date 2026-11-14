/**
 * @fileoverview 资源桑基图节点构建的数量守恒与无环校验测试。
 */
import {describe, expect, it} from 'vitest'
import {flowGraph} from './graph'
import type {ResourceFlowReport} from '../api/types'

const labels = {resource: (key: string) => key, task: (key: string) => key, stock: '库存', balance: '结余'}
function report(rows: ResourceFlowReport['flows']) {return {flows: rows} as ResourceFlowReport}
function row(resource: string, task: string, income: number, expense: number, evidence: 'confirmed' | 'adjustment' = 'confirmed') {return {resource, task, income, expense, evidence, operation: '', count: 1}}
describe('资源桑基图', () => {
  it('双侧任务节点不成环，数量守恒且保留真实数值', () => {
    const graph = flowGraph(report([row('Oil', 'Commission', 1000, 0), row('Oil', 'Main', 0, 1500)]), labels)
    const center = 'resource:Oil'
    expect(graph.links.filter(link => link.target === center).reduce((sum, link) => sum + link.amount, 0)).toBe(1500)
    expect(graph.links.filter(link => link.source === center).reduce((sum, link) => sum + link.amount, 0)).toBe(1500)
    expect(graph.nodes.find(node => node.name === 'stock:Oil')?.label).toBe('库存')
  })
  it('不同资源分别缩放，调整额明确标为待归因灰色节点', () => {
    const graph = flowGraph(report([row('Oil', 'Commission', 10000, 0), row('Gem', 'Commission', 10, 0), row('Gem', 'Unattributed', 300, 0, 'adjustment')]), labels)
    expect(graph.links.filter(link => link.target === 'resource:Oil').reduce((sum, link) => sum + link.value, 0)).toBe(100)
    expect(graph.links.filter(link => link.target === 'resource:Gem').reduce((sum, link) => sum + link.value, 0)).toBe(100)
    expect(graph.nodes.find(node => node.task === 'Unattributed')?.itemStyle?.color).toBe('#9299a1')
    expect(graph.nodes.filter(node => node.depth === 2).every(node => node.label === '结余')).toBe(true)
  })
  it('同一任务的收入与消费保持独立，零流量没有虚假节点', () => {
    const graph = flowGraph(report([row('Coin', 'Main', 600, 100), row('Gem', 'Main', 0, 0)]), labels)
    expect(graph.nodes.some(node => node.name === 'income:Coin:Main')).toBe(true)
    expect(graph.nodes.some(node => node.name === 'expense:Coin:Main')).toBe(true)
    expect(graph.nodes.some(node => node.resource === 'Gem')).toBe(false)
  })
})
