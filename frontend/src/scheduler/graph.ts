/**
 * @fileoverview 图编辑操作与端口校验，全部操作返回新文档以支持撤销。
 */
import type {CardDefinition, Catalog, Graph, PortType, ProgramDocument, ProgramNode, Subgraph} from './types'
import {compatiblePorts} from './appearance'

export const id = () => crypto.randomUUID()
export const clone = <T,>(value: T): T => structuredClone(value)
export const compatible = compatiblePorts
/** 兼容旧方案没有注释字段的节点：补上空串，让保存前后的文档表示一致。 */
export function withComments(doc: ProgramDocument): ProgramDocument {
  const nodes = (items: ProgramNode[]) => items.map(node => node.comment === undefined ? {...node,comment:''} : node)
  return {...doc,nodes:nodes(doc.nodes),subgraphs:doc.subgraphs.map(sub => ({...sub,nodes:nodes(sub.nodes)}))}
}
/** 通用端口已连接时显示对端类型；未连接时保留彩环，不把任意值伪装成某个具体类型。 */
export function connectedPortType(graph: Graph, doc: ProgramDocument, catalog: Catalog, nodeId: string, name: string, direction: 'inputs' | 'outputs', seen = new Set<string>()): PortType {
  const key = `${nodeId}:${direction}:${name}`
  if (seen.has(key)) return 'any'
  seen.add(key)
  const node = graph.nodes.find(n => n.id === nodeId)
  if (!node) return 'any'
  const type = definition(node,doc,catalog,graph)[direction].find(p => p.name === name)?.type ?? 'any'
  if (type !== 'any') return type
  for (const edge of graph.edges) {
    if (edge.kind !== 'data') continue
    const linked = direction === 'inputs' ? edge.target === nodeId && edge.targetPort === name : edge.source === nodeId && edge.sourcePort === name
    if (!linked) continue
    const peer = direction === 'inputs'
      ? connectedPortType(graph,doc,catalog,edge.source,edge.sourcePort,'outputs',seen)
      : connectedPortType(graph,doc,catalog,edge.target,edge.targetPort,'inputs',seen)
    if (peer !== 'any') return peer
  }
  return 'any'
}
/**
 * 解析节点的有效卡片定义：call 指向子图时改用子图签名，变量、子图端口与字面量节点动态合成，
 * 目录查不到时回落「未知」占位。
 */
export function definition(node: ProgramNode, doc: ProgramDocument, catalog: Catalog, graph: Graph): CardDefinition {
  const base = catalog.cards.find(c => c.type === node.type) ?? {type: node.type, label: node.type, category: '未知', pure: true, inputs: [], outputs: [], exits: [], params: {}}
  if (node.type === 'call') {
    const sub = doc.subgraphs.find(s => s.id === node.params.graph)
    if (sub) return {...base, category:'组合', label: sub.name, pure: sub.pure, inputs: sub.inputs, outputs: sub.outputs, exits: sub.pure ? [] : ['next']}
  }
  const sub = graph as Subgraph
  if (node.type.includes('variable')) {
    const variable = doc.variables.find(v => v.name === node.params.name)
    if (variable) return {...base, [node.type === 'get_variable' ? 'outputs' : 'inputs']: [{name:'value', type:variable.type, required:false}]}
  }
  if (node.type === 'input' && sub.inputs) {
    const port = sub.inputs.find(p => p.name === node.params.name)
    if (port) return {...base, outputs: [{...port, name: 'value'}]}
  }
  if (node.type === 'return' && sub.outputs) return {...base, inputs: sub.outputs}
  if (node.type === 'output' && sub.outputs) return {...base, inputs: sub.outputs, outputs: sub.outputs}
  if (node.type === 'literal') return {...base, outputs: [{name: 'value', required: false, type: (node.params.valueType ?? 'any') as PortType}]}
  return base
}
/** 用新图整体替换 main 或指定子图，返回新文档。 */
export function replaceGraph(doc: ProgramDocument, graphId: string, graph: Graph): ProgramDocument {
  return graphId === 'main' ? {...doc, ...graph} : {...doc, subgraphs: doc.subgraphs.map(s => s.id === graphId ? {...s, ...graph} : s)}
}
/**
 * 复制选中节点与两端都在选区内的连线：新 id 按「旧 id → 新 id」映射重接，
 * loop_end 与其循环卡片的配对关系跟随映射，位置整体右下偏移 40px。
 */
export function duplicate(graph: Graph, selection: Set<string>) {
  const ids = new Map([...selection].map(old => [old, id()]))
  return {
    nodes: graph.nodes.filter(n => selection.has(n.id)).map(n => ({...clone(n), id: ids.get(n.id)!, position: {x: n.position.x + 40, y: n.position.y + 40}, params: {...clone(n.params), ...(n.type === 'loop_end' && ids.has(String(n.params.loop)) ? {loop: ids.get(String(n.params.loop))} : {})}})),
    edges: graph.edges.filter(e => selection.has(e.source) && selection.has(e.target)).map(e => ({...e, id: id(), source: ids.get(e.source)!, target: ids.get(e.target)!})),
  }
}
/** 按连接依赖从左到右排布，循环返回由专门卡片表示，不添加可见回边。 */
export function horizontalLayout(graph: Graph): Graph {
  const indegree = new Map(graph.nodes.map(n => [n.id, 0]))
  const levels = new Map(graph.nodes.map(n => [n.id, 0]))
  const successors = new Map(graph.nodes.map(n => [n.id, new Set<string>()]))
  for (const edge of graph.edges) if (successors.has(edge.source) && indegree.has(edge.target) && !successors.get(edge.source)!.has(edge.target)) {
    successors.get(edge.source)!.add(edge.target)
    indegree.set(edge.target, indegree.get(edge.target)! + 1)
  }
  const queue = graph.nodes.filter(n => indegree.get(n.id) === 0).map(n => n.id)
  for (let index = 0; index < queue.length; index++) {
    const source = queue[index]!
    for (const target of successors.get(source)!) {
      levels.set(target, Math.max(levels.get(target)!, levels.get(source)! + 1))
      indegree.set(target, indegree.get(target)! - 1)
      if (indegree.get(target) === 0) queue.push(target)
    }
  }
  const rows = new Map<number, number>()
  return {...graph, nodes:graph.nodes.map(node => {
    const level = levels.get(node.id)!, row = rows.get(level) ?? 0
    rows.set(level, row + 1)
    return {...node, position:{x:level * 320, y:row * 640}}
  })}
}
/**
 * 把选中的卡片封装成子图并在原位留下一个 call 节点：跨界连线改接到 call 的 inputN/outputN 端口，
 * 纯度由选中卡片决定；选区含入口、返回或子图端口卡片、循环及其结束卡片拆散、纯组合无输出等
 * 非法情形直接抛错。
 */
export function encapsulate(doc: ProgramDocument, graphId: string, selected: Set<string>, name: string, catalog: Catalog) {
  const graph = graphId === 'main' ? doc : doc.subgraphs.find(s => s.id === graphId)!
  const picked = graph.nodes.filter(n => selected.has(n.id))
  if (!picked.length || picked.some(n => ['entry', 'return', 'input', 'output'].includes(n.type))) throw new Error('请选择逻辑卡片，入口和组合端口不能一起封装')
  const incoming = graph.edges.filter(e => !selected.has(e.source) && selected.has(e.target))
  const outgoing = graph.edges.filter(e => selected.has(e.source) && !selected.has(e.target))
  const controlIn = incoming.filter(e => e.kind === 'control')
  const controlOut = outgoing.filter(e => e.kind === 'control')
  const pure = picked.every(n => definition(n, doc, catalog, graph).pure)
  if (picked.some(n => n.type === 'loop_end' && !selected.has(String(n.params.loop))) || graph.nodes.some(n => n.type === 'loop_end' && selected.has(String(n.params.loop)) && !selected.has(n.id))) throw new Error('循环及其结束卡片必须一起封装')
  if (pure && !outgoing.some(e => e.kind === 'data')) throw new Error('数据组合至少需要一个连接到外部的输出')
  if (!pure && (new Set(controlIn.map(e => e.target)).size !== 1 || new Set(controlOut.map(e => e.target)).size > 1)) throw new Error('执行组合需要一个外部入口，出口应汇合到同一张后续卡片')
  const subId = id(), callId = id(), inputNodes: ProgramNode[] = [], inputs: Subgraph['inputs'] = [], outputs: Subgraph['outputs'] = []
  const internal = graph.edges.filter(e => selected.has(e.source) && selected.has(e.target)).map(clone)
  const parentEdges = graph.edges.filter(e => !selected.has(e.source) && !selected.has(e.target))
  incoming.filter(e => e.kind === 'data').forEach((e, index) => {
    const portName = `input${index + 1}`, inputId = id()
    const target = picked.find(n => n.id === e.target)!
    const type = definition(target, doc, catalog, graph).inputs.find(p => p.name === e.targetPort)?.type ?? 'any'
    inputs.push({name: portName, type, required: true})
    inputNodes.push({id: inputId, type: 'input', label: portName, params: {name: portName}, position: {x: 0, y: index * 130}})
    internal.push({...e, id: id(), source: inputId, sourcePort: 'value'})
    parentEdges.push({...e, id: id(), target: callId, targetPort: portName})
  })
  const outputId = id(), pairs = new Map<string, string>()
  outgoing.filter(e => e.kind === 'data').forEach(e => {
    const key = `${e.source}:${e.sourcePort}`
    let portName = pairs.get(key)
    if (!portName) {
      portName = `output${pairs.size + 1}`; pairs.set(key, portName)
      const source = picked.find(n => n.id === e.source)!
      const type = definition(source, doc, catalog, graph).outputs.find(p => p.name === e.sourcePort)?.type ?? 'any'
      outputs.push({name: portName, type, required: true})
      internal.push({...e, id: id(), target: outputId, targetPort: portName})
    }
    parentEdges.push({...e, id: id(), source: callId, sourcePort: portName})
  })
  const entryId = pure ? outputId : id()
  if (!pure) {
    internal.push({id: id(), source: entryId, sourcePort: 'next', target: controlIn[0]!.target, targetPort: 'in', kind: 'control'})
    for (const e of controlOut) internal.push({...e, id: id(), target: outputId, targetPort: 'in'})
    // 未连接的正常终点也返回组合，任务失败出口保持停止语义。
    for (const node of picked) for (const exit of definition(node, doc, catalog, graph).exits) {
      if (exit !== 'failed' && node.type !== 'loop_end' && !internal.some(e => e.kind === 'control' && e.source === node.id && e.sourcePort === exit)) internal.push({id:id(), source:node.id, sourcePort:exit, target:outputId, targetPort:'in', kind:'control'})
    }
    for (const e of controlIn) parentEdges.push({...e, target: callId})
    if (controlOut.length) parentEdges.push({...controlOut[0]!, id: id(), source: callId, sourcePort: 'next'})
  }
  const extra: ProgramNode[] = [{id: outputId, type: pure ? 'output' : 'return', label: '组合输出', params: {}, position: {x: 800, y: 100}}]
  if (!pure) extra.push({id: entryId, type: 'entry', label: '', params: {}, position: {x: 0, y: -160}})
  const sub: Subgraph = {id: subId, name, pure, inputs, outputs, entry: entryId, nodes: [...inputNodes, ...clone(picked), ...extra], edges: internal}
  const call: ProgramNode = {id: callId, type: 'call', label: name, params: {graph: subId}, position: picked[0]!.position}
  const result = replaceGraph(doc, graphId, {...graph, nodes: [...graph.nodes.filter(n => !selected.has(n.id)), call], edges: parentEdges})
  return {...result, subgraphs: [...result.subgraphs, sub]}
}
