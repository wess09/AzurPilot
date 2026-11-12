/**
 * @fileoverview 自定义调度的卡片画布：ReactFlow 包装，拖拽位置松手后才提交文档。
 */
import {useCallback, useEffect, useMemo, useRef, useState} from 'react'
import {applyEdgeChanges, applyNodeChanges, Background, Controls, MiniMap, ReactFlow, SelectionMode, useNodesInitialized, useReactFlow, type Edge, type EdgeChange, type Node, type NodeChange, type ReactFlowProps} from '@xyflow/react'
import {categoryColor} from './appearance'
import type {CardDefinition, Catalog, PortType, ProgramDocument, ProgramNode} from './types'

export type CanvasNode = Node<{card: ProgramNode; spec: CardDefinition; current: boolean; invalid: boolean; catalog: Catalog; document: ProgramDocument; connectedInputs: string[]; inputTypes: Record<string,PortType>; outputTypes: Record<string,PortType>; onParamsChange: (node: string, patch: Record<string, unknown>) => void}, 'card'>
type Props = ReactFlowProps<CanvasNode> & {onPositionsCommit: (nodes: CanvasNode[]) => void; focusEntry?: string}

/**
 * 调度程序画布。拖拽的瞬时状态由画布管理，松开后才经 onPositionsCommit 提交文档，
 * 避免测量、选择和持久图互相覆盖；focusEntry 在画布就绪后把视口对准入口卡片。
 */
export function ProgramCanvas({nodes: documentNodes = [], edges: documentEdges = [], onPositionsCommit, focusEntry, ...props}: Props) {
  const [nodes, setNodes] = useState(documentNodes)
  const [edges, setEdges] = useState(documentEdges)
  const root = useRef<HTMLDivElement>(null)
  const flow = useReactFlow<CanvasNode>()
  const nodesInitialized = useNodesInitialized()
  const focused = useRef(false)
  useEffect(() => {
    if (!focusEntry) {focused.current = false; return}
    if (!nodesInitialized || focused.current || !root.current) return
    const entry = documentNodes.find(node => node.id === focusEntry)
    if (!entry) return
    const frame = requestAnimationFrame(() => {
      const width = root.current?.clientWidth ?? 0
      const height = root.current?.clientHeight ?? 0
      if (!width || !height) return
      focused.current = true
      const zoom = width <= 980 ? 0.7 : 0.78
      const left = width <= 980 ? 48 : width <= 1200 ? 240 : 278
      void flow.setViewport({x:left - entry.position.x * zoom, y:Math.min(170, height * 0.22) - entry.position.y * zoom, zoom})
    })
    return () => cancelAnimationFrame(frame)
  }, [documentNodes, flow, focusEntry, nodesInitialized])
  // 同步外部文档变更：在渲染周期即时对齐节点与连线数据，避免 useEffect 异步帧延迟导致受控状态回弹。
  const [prevDocumentNodes, setPrevDocumentNodes] = useState(documentNodes)
  if (prevDocumentNodes !== documentNodes) {
    setPrevDocumentNodes(documentNodes)
    setNodes(previous => {
      const indexed = new Map(previous.map(node => [node.id, node]))
      return documentNodes.map(node => {
        const current = indexed.get(node.id)
        return {...current, ...node, position: current?.dragging ? current.position : node.position}
      })
    })
  }
  const [prevDocumentEdges, setPrevDocumentEdges] = useState(documentEdges)
  if (prevDocumentEdges !== documentEdges) {
    setPrevDocumentEdges(documentEdges)
    setEdges(previous => {
      const indexed = new Map(previous.map(edge => [edge.id, edge]))
      return documentEdges.map(edge => ({...indexed.get(edge.id), ...edge}))
    })
  }
  const onNodesChange = useCallback((changes: NodeChange<CanvasNode>[]) => {
    setNodes(previous => applyNodeChanges(changes, previous))
  }, [])
  const onEdgesChange = useCallback((changes: EdgeChange<Edge>[]) => setEdges(previous => applyEdgeChanges(changes,previous)), [])
  const minimapColor = useCallback((node: CanvasNode) => categoryColor(node.data.spec.category), [])
  const fitViewOptions = useMemo(() => ({padding: 0.12, minZoom: 0.2, maxZoom: 1}), [])
  return <div className="program-flow" ref={root}><ReactFlow<CanvasNode> {...props} nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
    fitView fitViewOptions={fitViewOptions} minZoom={0.2} maxZoom={1.6} autoPanOnNodeDrag={false} nodeDragThreshold={0}
    panOnDrag={[1,2]} panActivationKeyCode="Space" selectionOnDrag selectionMode={SelectionMode.Partial}
    multiSelectionKeyCode={['Shift','Control','Meta']} onNodeDragStop={(_, __, moved) => onPositionsCommit(moved)}
    onSelectionDragStop={(_, moved) => onPositionsCommit(moved)}>
    <Background gap={22} size={1}/><Controls showInteractive={false}/><MiniMap pannable zoomable nodeColor={minimapColor}/>
  </ReactFlow></div>
}
