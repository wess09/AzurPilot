/**
 * @fileoverview 资源流向桑基图组件：把资源流水报表交给 echarts 渲染，并随主题与语言重绘。
 */

import {useEffect, useMemo, useRef} from 'react'
import {init, use} from 'echarts/core'
import {SankeyChart} from 'echarts/charts'
import {TooltipComponent} from 'echarts/components'
import {SVGRenderer} from 'echarts/renderers'
import type {ResourceFlowReport} from '../api/types'
import {useApp} from '../app/context'
import {flowGraph, type FlowLink, type FlowNode} from './graph'

// echarts 按需注册：桑基图、提示框与 SVG 渲染器，注册一次即可。
use([SankeyChart, TooltipComponent, SVGRenderer])
/** 资源流向桑基图：用 echarts 渲染资源/任务的流量分布，点击节点回调 onPick 供上层跳转。布局由 flowGraph 预先算好，这里只做渲染。 */
export function Sankey({report, resourceLabel, taskLabel, onPick}: {report: ResourceFlowReport; resourceLabel: (key: string) => string; taskLabel: (key: string) => string; onPick: (resource: string, task?: string) => void}) {
  const {ui, resolvedMode, theme, language} = useApp(), container = useRef<HTMLDivElement>(null)
  const graph = useMemo(() => flowGraph(report, {resource: resourceLabel, task: taskLabel, stock: ui('flow.stock'), balance: ui('flow.balance')}), [report, resourceLabel, taskLabel, ui])
  useEffect(() => {
    const element = container.current!
    const chart = init(element, undefined, {renderer: 'svg'})
    // echarts 的 SVG 标签不认 CSS 变量，读出实际色值给标签；读不到时按深浅模式兜底。
    const color = getComputedStyle(element).getPropertyValue('--text').trim() || (resolvedMode === 'dark' ? '#eee' : '#333')
    chart.setOption({animation: false, tooltip: {trigger: 'item', renderMode: 'richText', confine: true, formatter: (value: {dataType: string; data: FlowLink | FlowNode}) => {
      if (value.dataType === 'edge') {const link = value.data as FlowLink; return `${resourceLabel(link.resource)} · ${link.label}\n${link.amount.toLocaleString()}`}
      const node = value.data as FlowNode
      return `${resourceLabel(node.resource!)} · ${node.label}${node.amount === undefined ? '' : `\n${node.amount.toLocaleString()}`}`
    }}, series: [{type: 'sankey', left: 12, right: 140, top: 12, bottom: 12, nodeWidth: 14, nodeGap: 20, draggable: false, nodeAlign: 'justify', emphasis: {focus: 'adjacency'}, label: {color, fontSize: 12, lineHeight: 15, formatter: (value: {data: FlowNode}) => `${value.data.label}${value.data.amount === undefined ? '' : `\n${value.data.amount.toLocaleString()}`}`}, data: graph.nodes, links: graph.links, lineStyle: {color: 'source', opacity: .3, curveness: .5}}]})
    chart.on('click', (value: unknown) => {const data = (value as {data: FlowNode}).data; if (data?.resource) onPick(data.resource, data.task)})
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(element)
    return () => {observer.disconnect(); chart.dispose()}
  }, [graph, resolvedMode, theme, language, onPick, resourceLabel])
  // 高度按节点最多的一列估：每个节点约 50px，下限 300px，避免列被压扁。
  return <div className="resource-sankey" ref={container} role="img" aria-label={ui('flow.sankey')} style={{height: Math.max(300, ...[0, 1, 2].map(depth => graph.nodes.filter(node => node.depth === depth).length * 50))}}/>
}
