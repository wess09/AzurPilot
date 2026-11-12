/**
 * @fileoverview 卡片式调度编辑器：图、属性、隔离模拟和运行轨迹。
 */
import {memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties} from 'react'
import {useParams} from 'react-router-dom'
import {ReactFlowProvider, Handle, MarkerType, Position, useConnection as useFlowConnection, useReactFlow, type NodeProps, type Connection as FlowConnection} from '@xyflow/react'
import {ArrowDown, ArrowLeft, ArrowUp, Bug, Copy, Download, FolderOpen, GripVertical, Layers, LocateFixed, Play, Plus, Redo2, Save, Search, StepForward, Trash2, Undo2, Upload, X} from 'lucide-react'
import '@xyflow/react/dist/style.css'
import '../scheduler/editor.css'
import {api} from '../api/client'
import {useApp, useConnection} from '../app/context'
import {ErrorBox, Loading} from '../components/ui'
import {clone, compatible, connectedPortType, definition, duplicate, encapsulate, horizontalLayout, id, replaceGraph, withComments} from '../scheduler/graph'
import {ProgramCanvas, type CanvasNode} from '../scheduler/Canvas'
import {categoryColor, controlColor, getCardIcon, portColors, wildcardBackground} from '../scheduler/appearance'
import {InlineParams} from '../scheduler/InlineParams'
import {editingText, editorCommand} from '../scheduler/shortcuts'
import type {Catalog, Graph, PortType, ProgramDocument, ProgramMode, ProgramNode, ProgramSaved, ProgramSimulation, ProgramState, ProgramValidation, Subgraph} from '../scheduler/types'
import type {UiKey} from '../i18n'

const typeLabels: Record<string, string> = {any:'任意值', number:'数值', boolean:'布尔', string:'文本', time:'时间', duration:'时长（秒）', resource:'资源记录', task:'任务', tasks:'任务列表', result:'任务结果', list:'列表', object:'对象'}
const exits: Record<string, string> = {next:'下一步', yes:'是', no:'否', unavailable:'数据不可用', completed:'完成', yielded:'主动让出', recoverable:'可恢复错误', failed:'失败', empty:'没有任务', success:'成功', body:'循环体', done:'结束'}
const labels: Record<string, string> = {name:'名称', value:'值', operator:'运算符', a:'输入 A', b:'输入 B', condition:'条件', yes:'满足时的值', no:'不满足时的值', seconds:'时长（秒）', time:'目标时间', start:'开始时刻', end:'结束时刻', weekdays:'星期（1～7）', field:'字段', maxAge:'有效期（秒）', autoRefresh:'过期时自动刷新', task:'任务', rule:'筛选规则', descending:'降序', count:'循环次数（-1 为持续）', loop:'所属循环', graph:'组合卡片', guard:'继续条件', key:'记录标识', kind:'记录类型', reset:'刷新时刻', limit:'每日上限', valueType:'数据类型'}
Object.assign(labels, {order:'当前优先级顺序', dueBefore:'到期截止时间', deadline:'最近计划时间', idleMode:'空闲策略', before:'到期截止时间', strict:'截止之前才视为到期'})
/** 画布节点卡片：按规格渲染标题、端口与内联参数。 */
const Card = memo(function Card({data, selected}: NodeProps<CanvasNode>) {
  const {card, spec} = data
  const CardIcon = getCardIcon(card.type, spec.category)
  const isEntry = spec.type === 'entry' || card.type === 'entry' || Boolean(spec.entry)
  const connection = useFlowConnection<CanvasNode>()
  const connectingPort = connection.fromHandle?.id?.replace(/^data:/,'')
  const connectingType = connectingPort && connection.fromNode?.data.outputTypes[connectingPort]
  // 连线进行中：any 输入端口实时显示来源类型配色，提示当前连接是否兼容。
  const handleStyle = (declared: PortType, actual: PortType, input: boolean) => {
    const type = declared === 'any' && input && connectingType ? connectingType : actual
    return {background:type === 'any' ? wildcardBackground : portColors[type]}
  }
  return <div style={{'--card-color':categoryColor(spec.category)} as CSSProperties} className={`program-card ${spec.pure ? 'data' : 'action'} ${selected ? 'selected' : ''} ${data.current ? 'current' : ''} ${data.invalid ? 'invalid' : ''}`}>
    <div className="program-card-heading">{!spec.pure && !isEntry && <Handle type="target" position={Position.Left} id="control:in" className="control-handle" style={{background:controlColor}} title="执行入口"/>}<span className="program-card-category">{spec.category} · {spec.pure ? '数据' : '执行'}</span><strong className="program-card-title"><CardIcon size={16} className="program-card-icon" aria-hidden="true"/>{spec.label}</strong>{card.label && <small className="program-card-alias">名称：{card.label}</small>}</div>
    {card.comment && <div className="program-card-comment">{card.comment}</div>}
    {spec.exits.length > 0 && <div className="program-card-exits">{spec.exits.map(exit => <div key={exit} className="program-port output exit-port"><span>{exits[exit] ?? exit}</span><Handle type="source" position={Position.Right} id={`control:${exit}`} className="control-handle" style={{background:controlColor}} title={`${exits[exit] ?? exit} · 执行`}/></div>)}</div>}
    <InlineParams
      card={card}
      spec={spec}
      catalog={data.catalog}
      document={data.document}
      connectedInputs={data.connectedInputs}
      inputTypes={data.inputTypes}
      outputTypes={data.outputTypes}
      handleStyle={handleStyle}
      onChange={data.onParamsChange}
    />
  </div>
})
const nodeTypes = {card: Card}

/** JSON 编辑域：草稿随外部值重置，失焦时解析；解析失败显示错误并保留输入。 */
function JsonField({label, value, onChange}: {label: string; value: unknown; onChange: (value: unknown) => void}) {
  const serialized = JSON.stringify(value ?? null, null, 2)
  const [draft, setDraft] = useState(serialized)
  const [error, setError] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {setDraft(serialized); setError('')}, [serialized])

  const autoResize = useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.max(el.scrollHeight + 4, 72)}px`
  }, [])

  useLayoutEffect(() => {
    const input = textareaRef.current
    if (!input) return
    autoResize()
    let width = input.clientWidth
    let frame = 0
    const observer = new ResizeObserver(() => {
      if (input.clientWidth !== width) {
        width = input.clientWidth
        cancelAnimationFrame(frame)
        frame = requestAnimationFrame(autoResize)
      }
    })
    observer.observe(input)
    return () => {observer.disconnect(); cancelAnimationFrame(frame)}
  }, [draft, autoResize])

  const calculatedRows = Math.min(Math.max((draft.match(/\n/g)?.length ?? 0) + 1, 3), 40)

  return <label onMouseEnter={autoResize}>{label}<textarea
    ref={textareaRef}
    className="program-json"
    rows={calculatedRows}
    value={draft}
    onFocus={autoResize}
    onChange={e => {setDraft(e.target.value); autoResize()}}
    onBlur={() => {
      try {onChange(JSON.parse(draft)); setError('')} catch {setError('请填写有效的 JSON 值')}
    }}
  />{error && <small role="alert">{error}</small>}</label>
}

/** 编辑器主体：画布、卡片库、属性面板与调试抽屉共用一份文档状态与撤销历史。 */
function Editor() {
  const {instance = ''} = useParams()
  const {notify, ui} = useApp()
  const connection = useConnection()
  const flow = useReactFlow<CanvasNode>()
  const [catalog, setCatalog] = useState<Catalog>()
  const [saved, setSaved] = useState<ProgramSaved>()
  const [doc, setDoc] = useState<ProgramDocument>()
  const [mode, setMode] = useState<ProgramMode>('takeover')
  const [graphId, setGraphId] = useState('main')
  const [search, setSearch] = useState('')
  const [selection, setSelection] = useState<string[]>([])
  const [validation, setValidation] = useState<ProgramValidation>()
  const [simulation, setSimulation] = useState<ProgramSimulation>()
  const [runtime, setRuntime] = useState<ProgramState>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [tab, setTab] = useState<'simulate' | 'runtime'>('simulate')
  const [simTime, setSimTime] = useState(() => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16))
  const [resources, setResources] = useState<Record<string, string>>({Oil:'8000', Coin:'50000', ActionPoint:'200'})
  const [apTotal, setApTotal] = useState('5300')
  const [simTasks, setSimTasks] = useState<Catalog['tasks']>()
  const [mobilePanel, setMobilePanel] = useState<'canvas' | 'library' | 'properties'>('canvas')
  const [compactEditor, setCompactEditor] = useState(false)
  const [canvasExpanded, setCanvasExpanded] = useState(false)
  const [outcomes, setOutcomes] = useState('completed')
  const [simSteps, setSimSteps] = useState(0)
  const [variablesOpen, setVariablesOpen] = useState(false)
  const [debugOpen, setDebugOpen] = useState(false)
  const [guideDismissed, setGuideDismissed] = useState(false)
  const [connector, setConnector] = useState({source:'', sourcePort:'', target:'', targetPort:''})
  const history = useRef<{past: ProgramDocument[]; future: ProgramDocument[]}>({past:[], future:[]})
  const clipboard = useRef<Pick<Graph,'nodes' | 'edges'> | undefined>(undefined)
  // 请求版本号：实例切换或再次操作时只有最新一次请求的结果才准写进状态，过期响应直接丢弃。
  const requestVersion = useRef(0)
  const wrapper = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    if (!doc || !wrapper.current) return
    setCompactEditor(wrapper.current.getBoundingClientRect().width <= 980)
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setCompactEditor(entry.contentRect.width <= 980)
    })
    observer.observe(wrapper.current)
    return () => observer.disconnect()
  }, [!!doc])
  const dirty = !!doc && !!saved && JSON.stringify(doc) !== JSON.stringify(saved.draft)
  // 渲染期同步 ref：回调里读最新文档与流程图 id，不依赖闭包的新旧。
  const docRef = useRef(doc)
  docRef.current = doc
  const graphIdRef = useRef(graphId)
  graphIdRef.current = graphId
  const graph = doc && (graphId === 'main' ? doc : doc.subgraphs.find(s => s.id === graphId))
  const picked = graph?.nodes.find(n => n.id === selection[0])

  useEffect(() => {
    if (connection !== 'ready') return
    let active = true
    const version = ++requestVersion.current
    setValidation(undefined); setSimulation(undefined); setSimSteps(0); setRuntime(undefined)
    setDoc(undefined); setError(''); setSelection([]); setGraphId('main'); history.current = {past:[], future:[]}
    void Promise.all([api.request('scheduler.program.catalog', {instance}), api.request('scheduler.program.get', {instance})]).then(([catalog, saved]) => {
      if (!active || version !== requestVersion.current) return
      setCatalog(catalog); setSaved(saved); setDoc(saved.draft); setSimTasks(catalog.tasks); setMode(saved.mode === 'native' ? 'takeover' : saved.mode)
    }).catch(error => {if (active) setError(error.message)})
    return () => {active = false}
  }, [instance, connection])
  useEffect(() => {
    if (connection !== 'ready') return
    let active = true, polling = false
    const poll = async () => {
      if (polling) return
      polling = true
      try {const result = await api.request('scheduler.program.state', {instance}); if (active) setRuntime(result.state)} catch { /* 重连后重新采样。 */ }
      finally {polling = false}
    }
    void poll(); const timer = setInterval(poll, 2000)
    return () => {active = false; clearInterval(timer)}
  }, [instance, connection])
  useEffect(() => {
    const guard = (event: BeforeUnloadEvent) => {if (dirty) {event.preventDefault(); event.returnValue = ''}}
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [dirty])

  const change = useCallback((next: ProgramDocument, track = true) => {
    if (doc && track) {history.current.past.push(clone(doc)); history.current.past = history.current.past.slice(-100); history.current.future = []}
    setDoc(withComments(next)); setValidation(undefined); setSimulation(undefined); setSimSteps(0)
  }, [doc])
  const updateGraph = (next: Graph, track = true) => {if (doc) change(replaceGraph(doc, graphId, next), track)}
  function undo(redo = false) {
    if (!doc) return
    const source = redo ? history.current.future : history.current.past
    const target = redo ? history.current.past : history.current.future
    const next = source.pop(); if (next) {target.push(clone(doc)); change(next, false); setSelection([]); if (graphId !== 'main' && !next.subgraphs.some(s => s.id === graphId)) setGraphId('main')}
  }
  function deleteSelected() {
    if (!graph) return
    const ids = new Set(selection.filter(n => n !== graph.entry))
    const selectedEdges = new Set(flow.getEdges().filter(e => e.selected).map(e => e.id))
    if (!ids.size && !selectedEdges.size) return
    updateGraph({...graph, nodes: graph.nodes.filter(n => !ids.has(n.id)), edges: graph.edges.filter(e => !ids.has(e.source) && !ids.has(e.target) && !selectedEdges.has(e.id))})
    setSelection([])
  }
  function copySelected(cut = false) {
    if (!graph) return
    const selected = new Set(selection.filter(n => graph.nodes.find(node => node.id === n)?.type !== 'entry'))
    if (!selected.size) return
    clipboard.current = {nodes:clone(graph.nodes.filter(n => selected.has(n.id))), edges:clone(graph.edges.filter(e => selected.has(e.source) && selected.has(e.target)))}
    void navigator.clipboard?.writeText(JSON.stringify({format:'azurpilot-scheduler-cards',...clipboard.current})).catch(() => {})
    if (cut) deleteSelected()
  }
  async function pasteSelected() {
    if (!graph) return
    let fragment = clipboard.current
    if (!fragment) {
      try {
        const value = JSON.parse(await navigator.clipboard.readText())
        if (value.format === 'azurpilot-scheduler-cards' && Array.isArray(value.nodes) && Array.isArray(value.edges) && value.nodes.every((n: ProgramNode) => typeof n.id === 'string' && typeof n.type === 'string' && n.params && Number.isFinite(n.position?.x) && Number.isFinite(n.position?.y))) fragment = value
      } catch { /* 系统剪贴板不可读时，仍支持本编辑器内复制粘贴。 */ }
    }
    if (!fragment) return
    const copied = duplicate({...graph,...fragment},new Set(fragment.nodes.map(n => n.id)))
    clipboard.current = copied
    updateGraph({...graph,nodes:[...graph.nodes,...copied.nodes],edges:[...graph.edges,...copied.edges]})
    setSelection(copied.nodes.map(n => n.id))
  }
  function add(kind: string, subId?: string, position?: {x:number; y:number}) {
    if (!catalog || !graph) return
    const spec = catalog.cards.find(c => c.type === kind)!
    const node: ProgramNode = {id:id(), type:kind, label:'', comment:'', params:{...clone(spec.params), ...(subId ? {graph:subId} : {})}, position:position ?? flow.screenToFlowPosition({x:(wrapper.current?.getBoundingClientRect().left ?? 0) + 360, y:(wrapper.current?.getBoundingClientRect().top ?? 0) + 180})}
    updateGraph({...graph, nodes:[...graph.nodes, node]}); setSelection([node.id])
    if (compactEditor) setMobilePanel('canvas')
  }
  function updateNode(node: ProgramNode) {
    if (graph) updateGraph({...graph, nodes:graph.nodes.map(n => n.id === node.id ? node : n)})
  }
  function focusStart() {
    if (!graph) return
    const entry = graph.nodes.find(node => node.id === graph.entry)
    const canvas = wrapper.current?.querySelector<HTMLElement>('.program-flow')
    if (!entry || !canvas) return
    const width = canvas.clientWidth
    const zoom = width <= 980 ? 0.7 : 0.78
    const left = width <= 980 ? 48 : width <= 1200 ? 240 : 278
    void flow.setViewport({x:left - entry.position.x * zoom, y:Math.min(170, canvas.clientHeight * 0.22) - entry.position.y * zoom, zoom}, {duration:220})
  }
  const connectValid = (link: {source: string; target: string; sourceHandle?: string | null; targetHandle?: string | null}) => {
    if (!graph || !doc || !catalog || link.source === link.target) return false
    const source = graph.nodes.find(n => n.id === link.source), target = graph.nodes.find(n => n.id === link.target)
    if (!source || !target || !link.sourceHandle || !link.targetHandle) return false
    const a = definition(source, doc, catalog, graph), b = definition(target, doc, catalog, graph)
    const [kind, port] = link.sourceHandle.split(':'); const [other, input] = link.targetHandle.split(':')
    if (kind !== other) return false
    if (kind === 'control') return a.exits.includes(port!) && !b.pure && b.type !== 'entry' && !b.entry && input === 'in'
    const output = a.outputs.find(p => p.name === port), incoming = b.inputs.find(p => p.name === input)
    return !!output && !!incoming && compatible(output.type, incoming.type)
  }
  function connect(link: FlowConnection) {
    if (!graph || !connectValid(link)) {notify('连接端口不兼容', true); return}
    const [kind, sourcePort] = link.sourceHandle!.split(':')
    const targetPort = link.targetHandle!.split(':')[1]!
    // 端口独占：数据边一个输入口只接一条；控制边一个输出口只发一条，落新边前先摘掉同口旧边。
    const edges = graph.edges.filter(e => kind === 'data' ? !(e.target === link.target && e.targetPort === targetPort && e.kind === kind) : !(e.source === link.source && e.sourcePort === sourcePort && e.kind === kind))
    updateGraph({...graph, edges:[...edges, {id:id(), source:link.source, sourcePort:sourcePort!, target:link.target, targetPort, kind:kind as 'data' | 'control'}]})
  }
  const onParamsChange = useCallback((node: string, patch: Record<string, unknown>) => {
    const currentDoc = docRef.current
    if (!currentDoc) return
    const gid = graphIdRef.current
    const currentGraph = gid === 'main' ? currentDoc : currentDoc.subgraphs.find(s => s.id === gid)
    if (!currentGraph) return
    change(replaceGraph(currentDoc, gid, {...currentGraph, nodes:currentGraph.nodes.map(n => n.id === node ? {...n, params:{...n.params, ...patch}} : n)}))
  }, [change])
  const currentNode = (tab === 'simulate' ? simulation?.state.node : runtime?.node)
  const nodes = useMemo<CanvasNode[]>(() => graph && catalog && doc ? graph.nodes.map(node => {
    const spec = definition(node,doc,catalog,graph)
    return {id:node.id,type:'card',position:node.position,selected:selection.includes(node.id),data:{card:node,spec,current:currentNode === node.id,invalid:!!validation?.diagnostics.some(d => d.node === node.id && d.graph === graphId),catalog,document:doc,onParamsChange,connectedInputs:graph.edges.filter(e => e.kind === 'data' && e.target === node.id).map(e => e.targetPort),inputTypes:Object.fromEntries(spec.inputs.map(p => [p.name,connectedPortType(graph,doc,catalog,node.id,p.name,'inputs')])),outputTypes:Object.fromEntries(spec.outputs.map(p => [p.name,connectedPortType(graph,doc,catalog,node.id,p.name,'outputs')]))}}
  }) : [], [graph, catalog, doc, selection, currentNode, validation, graphId,onParamsChange])
  const edges = useMemo(() => graph && catalog && doc ? graph.edges.map(e => {
    const color = e.kind === 'control' ? controlColor : portColors[connectedPortType(graph,doc,catalog,e.source,e.sourcePort,'outputs')]
    return {id:e.id, source:e.source, target:e.target, sourceHandle:`${e.kind}:${e.sourcePort}`, targetHandle:`${e.kind}:${e.targetPort}`, label:e.kind === 'control' ? exits[e.sourcePort] ?? e.sourcePort : undefined, className:e.kind === 'control' ? 'program-control-edge' : 'program-data-edge', style:{stroke:color, strokeWidth:e.kind === 'control' ? 2.5 : 1.5}, markerEnd:e.kind === 'control' ? {type:MarkerType.ArrowClosed, color} : undefined, type:'smoothstep'}
  }) : [], [graph, catalog, doc])
  const onSelectionChange = useCallback(({nodes}: {nodes: CanvasNode[]}) => setSelection(previous => {
    const next = nodes.map(n => n.id)
    return previous.length === next.length && previous.every((value, index) => value === next[index]) ? previous : next
  }), [])

  async function action(kind: 'save' | 'apply' | 'native' | 'validate') {
    if (!doc || !saved) return
    const version = requestVersion.current
    setBusy(true); setError('')
    try {
      if (kind === 'validate') {
        setDebugOpen(true)
        const result = await api.request('scheduler.program.validate', {instance, document:doc, mode}); if (version === requestVersion.current) setValidation(result)
      } else {
        let latest = saved
        if (kind !== 'native') latest = await api.request('scheduler.program.save', {instance, revision:saved.revision, document:doc})
        if (version === requestVersion.current) setSaved(latest)
        if (kind === 'apply' || kind === 'native') latest = await api.request('scheduler.program.apply', {instance, revision:latest.revision, mode:kind === 'native' ? 'native' : mode})
        if (version === requestVersion.current) {setSaved(latest); notify(kind === 'save' ? '草稿已保存' : kind === 'native' ? '已切回原调度' : '方案已应用，将在安全边界生效')}
      }
    } catch (error) {if (version === requestVersion.current) {setError((error as Error).message); const details = (error as {details?: ProgramValidation['diagnostics']}).details; if (Array.isArray(details)) setValidation({valid:false, diagnostics:details})}}
    finally {if (version === requestVersion.current) setBusy(false)}
  }
  async function simulate(steps: number) {
    if (!doc) return
    setBusy(true); setError(''); setTab('simulate'); setDebugOpen(true)
    const version = requestVersion.current
    try {
      const now = simTime.replace('T', ' ') + ':00'
      const injected = Object.fromEntries(Object.entries(resources).filter(([,value]) => value !== '').map(([name, value]) => [name, {name, value:Number(value), total:name === 'ActionPoint' ? Number(apTotal) : null, observedAt:now, status:'fresh', source:'simulation'}]))
      const results = outcomes.split(',').map(x => x.trim()).filter(Boolean) as Array<'completed' | 'yielded' | 'recoverable' | 'failed'>
      const result = await api.request('scheduler.program.simulate', {instance, document:doc, mode, context:{now, resources:injected, tasks:simTasks}, outcomes:results, steps})
      if (version === requestVersion.current) {setSimulation(result); setValidation(result); setSimSteps(steps)}
    } catch (error) {if (version === requestVersion.current) setError((error as Error).message)} finally {if (version === requestVersion.current) setBusy(false)}
  }

  if (!doc || !catalog || !graph || !saved) return error ? <ErrorBox message={error}/> : <Loading/>
  const spec = picked && definition(picked, doc, catalog, graph)
  const changeParam = (key: string, value: unknown) => {if (picked) updateNode({...picked, params:{...picked.params, [key]:value, ...(key === 'valueType' ? {value:value === 'boolean' ? false : value === 'number' || value === 'duration' ? 0 : value === 'list' || value === 'tasks' ? [] : ['object','resource','task','result'].includes(String(value)) ? {} : ''} : {})}})}
  const currentGraph = graph as Subgraph
  const sourceNode = graph.nodes.find(n => n.id === connector.source), targetNode = graph.nodes.find(n => n.id === connector.target)
  const sourceSpec = sourceNode && definition(sourceNode, doc, catalog, graph), targetSpec = targetNode && definition(targetNode, doc, catalog, graph)
  const renderParams = Object.entries({...spec?.params, ...picked?.params})
  const status = (tab === 'simulate' ? simulation?.state : runtime)

  return <div className={`program-editor ${compactEditor ? 'is-compact' : ''}`} ref={wrapper} onKeyDown={event => {
    if (editingText(event.target)) return
    const command = editorCommand(event)
    if (!command) return
    event.preventDefault(); event.stopPropagation()
    // 删除选中节点后，焦点不能随节点或框选层一同消失，否则紧接着的撤销会落到页面外。
    wrapper.current?.querySelector<HTMLElement>('.program-canvas')?.focus({preventScroll:true})
    if (command === 'copy') copySelected()
    else if (command === 'cut') copySelected(true)
    else if (command === 'paste') void pasteSelected()
    else if (command === 'undo' || command === 'redo') undo(command === 'redo')
    else if (command === 'delete') deleteSelected()
    else if (command === 'all') setSelection(graph.nodes.map(n => n.id))
    else if (command === 'clear') setSelection([])
  }}>
    <header className="program-toolbar"><div><Layers size={21}/><div><h1>{ui('nav.schedulerProgram')}</h1><small>{saved.mode === 'native' ? '当前使用原调度' : saved.mode === 'enhance' ? '当前使用增强调度' : '当前由卡片程序完全接管'} · {dirty ? '有未保存修改' : '草稿已保存'}</small></div></div>
      <div className="program-actions"><button className="button secondary" onClick={() => undo()} disabled={!history.current.past.length} title="撤销"><Undo2 size={15}/></button><button className="button secondary" onClick={() => undo(true)} disabled={!history.current.future.length} title="重做"><Redo2 size={15}/></button>
        <select aria-label="调度模式" value={mode} onChange={e => {setMode(e.target.value as ProgramMode); setValidation(undefined)}}><option value="takeover">完全接管</option><option value="enhance">增强调度</option></select>
        <button className="button secondary" disabled={busy} onClick={() => void action('validate')}>校验</button>
        <button type="button" className={`button secondary program-debug-btn ${debugOpen ? 'active' : ''}`} onClick={() => setDebugOpen(open => !open)} title={debugOpen ? '收起调试面板' : '展开调试面板'} aria-expanded={debugOpen}><Bug size={14}/><span>调试</span></button>
        <button className="button secondary" disabled={busy} onClick={() => void action('save')}><Save size={15}/>保存草稿</button><button className="button primary" disabled={busy} onClick={() => void action('apply')}><Play size={15}/>应用方案</button>
      </div>
    </header>
    {error && <ErrorBox message={error}/>}
    <div className="program-subtoolbar"><input aria-label="方案名称" value={doc.name} onChange={e => change({...doc, name:e.target.value})}/><select aria-label="编辑流程" value={graphId} onChange={e => {setGraphId(e.target.value); setSelection([]); setTimeout(() => void flow.fitView(), 0)}}><option value="main">主程序</option>{doc.subgraphs.map(s => <option key={s.id} value={s.id}>{s.name}{s.pure ? ' · 数据' : ' · 执行'}</option>)}</select>
      <button className="button secondary" onClick={focusStart} title="将程序入口移回可视区域"><LocateFixed size={14}/>定位入口</button>
      <button className="button secondary" onClick={() => {change(clone(catalog.templates[mode === 'enhance' ? 'enhance' : 'takeover'])); setGraphId('main'); setSelection([])}}><FolderOpen size={14}/>载入原调度方案</button>
      {catalog.templates && 'all' in catalog.templates && <button className="button secondary" onClick={() => {change(clone(catalog.templates.all)); setGraphId('main'); setSelection([]); setTimeout(() => void flow.fitView({padding:0.12}), 0)}}><Layers size={14}/>全卡片排列</button>}
      <button className="button secondary" onClick={() => setVariablesOpen(!variablesOpen)}>变量与端口</button>
      <button className="button secondary" onClick={() => {updateGraph(horizontalLayout(graph)); requestAnimationFrame(() => void flow.fitView({padding:0.12}))}}>从左到右排列</button>
      <button className="button secondary" onClick={() => setCanvasExpanded(value => !value)}>{canvasExpanded ? '显示面板' : '展开画布'}</button>
      <button className="button secondary" onClick={() => copySelected()} disabled={!selection.length} title="复制（Ctrl/Cmd+C）"><Copy size={14}/>复制</button>
      <button className="button secondary" onClick={() => void pasteSelected()} title="粘贴（Ctrl/Cmd+V）">粘贴</button>
      <button className="button secondary" disabled={!selection.length} onClick={() => {try {change(encapsulate(doc, graphId, new Set(selection), '自定义组合卡片', catalog)); setSelection([])} catch (error) {notify((error as Error).message, true)}}}>封装卡片</button>
      <button className="button secondary" disabled={!selection.length} onClick={deleteSelected} title="删除选中卡片"><Trash2 size={14}/></button>
      <button className="button secondary" onClick={() => {const blob = new Blob([JSON.stringify(doc, null, 2)], {type:'application/json'}); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `${doc.name}.scheduler.json`; link.click(); URL.revokeObjectURL(url)}}><Download size={14}/>导出</button>
      <label className="button secondary program-file"><Upload size={14}/>导入<input type="file" accept="application/json" onChange={event => {const file = event.target.files?.[0]; if (file) void file.text().then(text => {const next = JSON.parse(text) as ProgramDocument; if (next.schemaVersion !== 1 || !Array.isArray(next.nodes) || !Array.isArray(next.subgraphs)) throw new Error('不是版本 1 的调度文档'); change(next); setGraphId('main'); setSelection([])}).catch(error => notify(error.message, true)); event.target.value = ''}}/></label>
      {saved.mode !== 'native' && <button className="button secondary" disabled={busy} onClick={() => void action('native')}>切回原调度</button>}
    </div>
    {variablesOpen && <section className="program-schema-panel">
      <div><strong>变量</strong><button className="button secondary" onClick={() => change({...doc, variables:[...doc.variables, {name:`variable${doc.variables.length + 1}`, type:'number', initial:0, persistent:false}]})}><Plus size={13}/>添加</button></div>
      {doc.variables.map((v, index) => <div className="program-schema-row" key={index}><input aria-label="变量名称" value={v.name} onChange={e => change({...doc, variables:doc.variables.map((x, i) => i === index ? {...x, name:e.target.value} : x)})}/><select value={v.type} aria-label="变量类型" onChange={e => change({...doc, variables:doc.variables.map((x, i) => i === index ? {...x, type:e.target.value as PortType} : x)})}>{Object.entries(typeLabels).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select><JsonField label="初始值" value={v.initial} onChange={value => change({...doc, variables:doc.variables.map((x,i) => i === index ? {...x, initial:value} : x)})}/><label><input type="checkbox" checked={v.persistent} onChange={e => change({...doc, variables:doc.variables.map((x,i) => i === index ? {...x, persistent:e.target.checked} : x)})}/>重启保留</label><button onClick={() => change({...doc, variables:doc.variables.filter((_,i) => i !== index)})}><Trash2 size={14}/></button></div>)}
      {graphId !== 'main' && <><label>组合名称<input value={currentGraph.name} onChange={e => change({...doc, subgraphs:doc.subgraphs.map(s => s.id === graphId ? {...s, name:e.target.value} : s)})}/></label><label><input type="checkbox" checked={currentGraph.pure} onChange={e => change({...doc, subgraphs:doc.subgraphs.map(s => s.id === graphId ? {...s, pure:e.target.checked} : s)})}/>无副作用数据组合</label>
        {(['inputs','outputs'] as const).map(kind => <div key={kind}><strong>{kind === 'inputs' ? '输入端口' : '输出端口'}</strong><button onClick={() => change({...doc, subgraphs:doc.subgraphs.map(s => s.id === graphId ? {...s, [kind]:[...s[kind], {name:`${kind}${s[kind].length + 1}`, type:'any', required:true}]} : s)})}>添加端口</button>{currentGraph[kind].map((p,index) => <div className="program-schema-row" key={index}><input aria-label="端口名称" value={p.name} onChange={e => change({...doc, subgraphs:doc.subgraphs.map(s => s.id === graphId ? {...s, [kind]:s[kind].map((x,i) => i === index ? {...x, name:e.target.value} : x)} : s)})}/><select value={p.type} aria-label="端口类型" onChange={e => change({...doc, subgraphs:doc.subgraphs.map(s => s.id === graphId ? {...s, [kind]:s[kind].map((x,i) => i === index ? {...x, type:e.target.value} : x)} : s)})}>{Object.entries(typeLabels).map(([key,label]) => <option key={key} value={key}>{label}</option>)}</select><button onClick={() => change({...doc, subgraphs:doc.subgraphs.map(s => s.id === graphId ? {...s, [kind]:s[kind].filter((_,i) => i !== index)} : s)})}>删除</button></div>)}</div>)}</>}
    </section>}
    <div className="program-mobile-panels">
      <button type="button" className={`button ${mobilePanel === 'canvas' ? 'primary active' : 'secondary'}`} onClick={() => setMobilePanel('canvas')}>画布</button>
      <button type="button" className={`button ${mobilePanel === 'library' ? 'primary active' : 'secondary'}`} onClick={() => setMobilePanel('library')}>卡片库</button>
      <button type="button" className={`button ${mobilePanel === 'properties' ? 'primary active' : 'secondary'}`} onClick={() => setMobilePanel('properties')}>属性与连接</button>
    </div>
    <div className={`program-workspace mobile-${mobilePanel} ${canvasExpanded ? 'canvas-expanded' : ''} ${picked ? 'has-selection' : ''}`}>
      <main className="program-canvas" tabIndex={0} aria-label="调度画布" onPointerDown={event => {if (!editingText(event.target)) event.currentTarget.focus({preventScroll:true})}} onDragOver={e => {e.preventDefault(); e.dataTransfer.dropEffect = 'copy'}} onDrop={e => {e.preventDefault(); try {const data = JSON.parse(e.dataTransfer.getData('application/azurpilot-card')); add(data.type, data.graph, flow.screenToFlowPosition({x:e.clientX,y:e.clientY}))} catch { /* 忽略非卡片拖放。 */ }}}>
        <ProgramCanvas key={graphId} nodes={nodes} edges={edges} focusEntry={graphId === 'main' && graph.edges.some(e => e.kind === 'control') && graph.nodes.some(n => n.type === 'original_settings') ? graph.entry : undefined} nodeTypes={nodeTypes} deleteKeyCode={null} onNodeClick={() => {if (compactEditor) setMobilePanel('properties')}} onSelectionChange={onSelectionChange} onConnect={connect} isValidConnection={connectValid}
          onPositionsCommit={moved => {const positions = new Map(moved.map(n => [n.id, n.position])); if (moved.some(n => {const old=graph.nodes.find(x => x.id === n.id); return old && (old.position.x !== n.position.x || old.position.y !== n.position.y)})) updateGraph({...graph, nodes:graph.nodes.map(n => positions.has(n.id) ? {...n, position:positions.get(n.id)!} : n)})}}
          onEdgesDelete={deleted => updateGraph({...graph, edges:graph.edges.filter(e => !deleted.some(d => d.id === e.id))})}
          onEdgeDoubleClick={(_,edge) => updateGraph({...graph, edges:graph.edges.filter(e => e.id !== edge.id)})}/>
        <div className="program-canvas-hint">左键框选 · 中键或空格拖动 · Ctrl/Cmd+C/V 复制粘贴 · 退格删除<br/>同色端口可连接 · 彩环为通用端口 · 方形为执行端口</div>
      </main>
      <aside className="program-library nowheel nopan nodrag">
        <div className="program-mobile-back-bar">
          <button type="button" className="button secondary program-mobile-back" onClick={() => setMobilePanel('canvas')}>
            <ArrowLeft size={14}/>返回画布
          </button>
        </div>
        <label className="program-search"><Search size={15}/><input placeholder="搜索卡片…" value={search} onChange={e => setSearch(e.target.value)}/></label>
        {[...new Set(catalog.cards.map(c => c.category))].map(category => <div key={category} style={{'--card-color':categoryColor(category)} as CSSProperties}><h3><i className="program-category-dot"/>{category}</h3>{catalog.cards.filter(c => c.category === category && `${c.label} ${c.type}`.toLowerCase().includes(search.toLowerCase())).map(card => {
          const Icon = getCardIcon(card.type, card.category)
          return <button key={card.type} draggable onDragStart={event => event.dataTransfer.setData('application/azurpilot-card', JSON.stringify({type:card.type}))} onClick={() => add(card.type)}><Icon size={14} aria-hidden="true"/>{card.label}</button>
        })}</div>)}
        <h3>组合卡片</h3>{doc.subgraphs.filter(s => s.name.includes(search)).map(sub => <div className="program-library-composite" key={sub.id}><button draggable onDragStart={event => event.dataTransfer.setData('application/azurpilot-card', JSON.stringify({type:'call', graph:sub.id}))} onClick={() => add('call', sub.id)}><Layers size={14} aria-hidden="true"/>{sub.name}</button><button title="打开内部逻辑" onClick={() => {setGraphId(sub.id); setSelection([])}}>↗</button></div>)}
      </aside>
      <aside className="program-properties nowheel nopan nodrag">
        <div className="program-properties-title-row">
          <h2>{picked && spec ? <>{(() => {const PickedIcon = getCardIcon(picked.type, spec.category); return <PickedIcon size={16} className="program-properties-icon" style={{color:categoryColor(spec.category)}} aria-hidden="true"/>})()}{spec.label}</> : '卡片属性'}</h2>
          <button type="button" className="button secondary program-mobile-back" onClick={() => setMobilePanel('canvas')}>
            <ArrowLeft size={14}/>返回画布
          </button>
        </div>
        {picked?.label && <div className="program-card-alias" style={{marginBottom:10}}>别名：{picked.label}</div>}
        {!picked && <p className="muted">点击卡片设置参数。拖拽端口连线，也可以使用下方的连接表单。</p>}
        {picked && <><label htmlFor="program-card-label">卡片名称<input id="program-card-label" aria-label="卡片名称" placeholder="自定义别名（优先显示原名）" value={picked.label} onChange={e => updateNode({...picked, label:e.target.value})}/></label>
          <label htmlFor="program-card-comment">卡片注释<textarea id="program-card-comment" aria-label="卡片注释" value={picked.comment ?? ''} rows={Math.max((picked.comment?.match(/\n/g)?.length ?? 0) + 1, 3)} maxLength={2000} placeholder="单独设置卡片注释，说明具体用途…" onChange={e => updateNode({...picked, comment:e.target.value})}/></label>
          {picked.type === 'call' && <button className="button secondary" onClick={() => {setGraphId(String(picked.params.graph)); setSelection([])}}>打开内部逻辑</button>}
          {graphId !== 'main' && currentGraph.pure && <button className="button secondary" onClick={() => updateGraph({...graph, entry:picked.id})}>作为数据输出入口</button>}
          {renderParams.map(([key,value]) => {
            if (key === 'overrides') return <div key={key}><h3>本次任务参数</h3>{Object.entries(catalog.overrides).map(([param,kind]) => <label key={param}>{param}<input placeholder="沿用任务配置" value={String((value as Record<string, unknown>)?.[param] ?? '')} onChange={e => {const next = {...value as object}; if (e.target.value === '') delete (next as Record<string,unknown>)[param]; else (next as Record<string,unknown>)[param] = kind === 'integer' ? Number(e.target.value) : e.target.value; changeParam(key, next)}}/></label>)}</div>
            if (key === 'order') return <div key={key}><h3>任务优先级</h3>{(value as string[]).map((task,index,list) => <div className="program-priority-row" key={`${task}-${index}`} draggable onDragStart={e => e.dataTransfer.setData('text/priority-index', String(index))} onDragOver={e => e.preventDefault()} onDrop={e => {e.preventDefault(); const raw = e.dataTransfer.getData('text/priority-index'); if (!raw.trim()) return; const from = Number(raw); if (!Number.isInteger(from) || from < 0 || from >= list.length) return; const next = [...list]; const [moved] = next.splice(from,1); if (moved) {next.splice(index,0,moved); changeParam(key,next)}}}><GripVertical size={14}/><span>{task}</span><button disabled={index === 0} title="提高优先级" onClick={() => {const next=[...list]; [next[index-1],next[index]]=[next[index]!,next[index-1]!]; changeParam(key,next)}}><ArrowUp size={13}/></button><button disabled={index === list.length-1} title="降低优先级" onClick={() => {const next=[...list]; [next[index],next[index+1]]=[next[index+1]!,next[index]!]; changeParam(key,next)}}><ArrowDown size={13}/></button><button title="移除优先级" onClick={() => changeParam(key,list.filter((_,i) => i !== index))}><Trash2 size={13}/></button></div>)}<select aria-label="添加优先级任务" value="" onChange={e => {if (e.target.value) changeParam(key,[...value as string[],e.target.value])}}><option value="">添加任务…</option>{catalog.tasks.filter(t => !(value as string[]).includes(t.name)).map(t => <option key={t.name}>{t.name}</option>)}</select></div>
            if (key === 'resources' || key === 'names') return <fieldset key={key}><legend>{key === 'resources' ? '资源' : '指定任务（空为全部）'}</legend>{(key === 'resources' ? catalog.resources : catalog.tasks).map(item => <label key={item.name}><input type="checkbox" checked={(value as string[]).includes(item.name)} onChange={e => changeParam(key,e.target.checked ? [...value as string[],item.name] : (value as string[]).filter(x => x !== item.name))}/>{item.name}</label>)}</fieldset>
            let options: string[] | undefined
            if (key === 'graph' || key === 'guard') options = doc.subgraphs.filter(s => key !== 'guard' || s.pure).map(s => s.id)
            else if (key === 'task' || (key === 'name' && picked.type === 'task')) options = catalog.tasks.map(t => t.name)
            else if (key === 'name' && picked.type === 'resource') options = catalog.resources.map(r => r.name)
            else if (key === 'name' && picked.type.includes('variable')) options = doc.variables.map(v => v.name)
            else if (key === 'loop') options = graph.nodes.filter(n => ['loop','foreach'].includes(n.type)).map(n => n.id)
            else if (key === 'operator') options = picked.type === 'logic' ? ['and','or','not'] : picked.type === 'math' ? ['+','-','*','/','%','min','max'] : ['==','!=','>','>=','<','<=']
            else if (key === 'rule') options = ['enabled','due','field']
            else if (key === 'kind') options = ['quota','cooldown']
            else if (key === 'valueType') options = Object.keys(typeLabels)
            else if (key === 'field' && picked.type === 'resource') options = ['value','limit','total']
            if (options) {
              const optionLabel = (opt: string) => {
                const sub = doc.subgraphs.find(s => s.id === opt)
                if (sub) return sub.name
                const target = graph.nodes.find(n => n.id === opt)
                if (target) {
                  const orig = definition(target, doc, catalog, graph).label
                  return target.label ? `${orig}（${target.label}）` : orig
                }
                return opt
              }
              return <label key={key}>{labels[key] ?? key}<select value={String(value)} onChange={e => changeParam(key,e.target.value)}><option value="">未设置</option>{options.map(option => <option key={option} value={option}>{optionLabel(option)}</option>)}</select></label>
            }
            if (typeof value === 'boolean') return <label className="program-checkbox" key={key}><input type="checkbox" checked={value} onChange={e => changeParam(key,e.target.checked)}/>{labels[key] ?? key}</label>
            if (typeof value === 'number' || typeof value === 'string') return <label key={key}>{labels[key] ?? key}<input type={typeof value === 'number' ? 'number' : 'text'} value={value} onChange={e => changeParam(key,typeof value === 'number' ? Number(e.target.value) : e.target.value)}/></label>
            return <JsonField key={key} label={labels[key] ?? key} value={value} onChange={next => changeParam(key,next)}/>
          })}
          {spec?.inputs.filter(p => !renderParams.some(([key]) => key === p.name)).map(p => <JsonField key={p.name} label={`${p.name} · ${typeLabels[p.type]}（可用连线代替）`} value={picked.params[p.name]} onChange={value => changeParam(p.name,value)}/>)}
          {picked.type === 'resource' && status?.resources?.[String(picked.params.name)] && <pre className="program-observation">{JSON.stringify(status.resources[String(picked.params.name)],null,2)}</pre>}{picked.type === 'resource' && <small>{catalog.resources.find(r => r.name === picked.params.name)?.refreshable ? '支持在任务边界主动刷新' : '使用任务观察记录，不支持主动刷新'}</small>}
        </>}
        <details className="program-connect"><summary>按钮式连接</summary><label>来源卡片<select aria-label="来源卡片" value={connector.source} onChange={e => setConnector({...connector,source:e.target.value,sourcePort:''})}><option value="">选择来源…</option>{graph.nodes.map(n => <option key={n.id} value={n.id}>{definition(n,doc,catalog,graph).label}{n.label ? `（${n.label}）` : ''} · {n.id.slice(0,7)}</option>)}</select></label><label>输出端口<select aria-label="输出端口" value={connector.sourcePort} onChange={e => setConnector({...connector,sourcePort:e.target.value})}><option value="">选择输出…</option>{sourceSpec?.outputs.map(p => <option key={p.name} value={`data:${p.name}`}>{p.name} · {typeLabels[p.type]}</option>)}{sourceSpec?.exits.map(e => <option key={e} value={`control:${e}`}>{exits[e] ?? e} · 执行</option>)}</select></label><label>目标卡片<select aria-label="目标卡片" value={connector.target} onChange={e => setConnector({...connector,target:e.target.value,targetPort:''})}><option value="">选择目标…</option>{graph.nodes.map(n => <option key={n.id} value={n.id}>{definition(n,doc,catalog,graph).label}{n.label ? `（${n.label}）` : ''} · {n.id.slice(0,7)}</option>)}</select></label><label>输入端口<select aria-label="输入端口" value={connector.targetPort} onChange={e => setConnector({...connector,targetPort:e.target.value})}><option value="">选择输入…</option>{targetSpec?.inputs.map(p => <option key={p.name} value={`data:${p.name}`}>{p.name} · {typeLabels[p.type]}</option>)}{targetSpec && !targetSpec.pure && targetSpec.type !== 'entry' && !targetSpec.entry && <option value="control:in">执行入口</option>}</select></label><button className="button secondary" onClick={() => connect({source:connector.source,target:connector.target,sourceHandle:connector.sourcePort,targetHandle:connector.targetPort})}>连接</button></details>
      </aside>
      {!guideDismissed && graph.edges.some(e => e.kind === 'control') && graph.nodes.some(n => n.type === 'original_settings') && (
        <div className="program-default-guide">
          <span>原调度业务流程：读取任务 → 过滤启用与到期状态 → 按当前实例优先级排序 → 执行；没有到期任务时等待最近计划。任务结束后立即重新判断。维护检测、登录恢复和运行监护由原执行器处理。</span>
          <button type="button" className="program-guide-close" title="关闭说明" onClick={() => setGuideDismissed(true)}><X size={13}/></button>
        </div>
      )}
      <aside className={`program-console program-debug-drawer nowheel nopan nodrag ${debugOpen ? 'open' : 'closed'}`} aria-label="调试面板" onWheel={e => e.stopPropagation()}>
        <div className="program-console-tabs">
          <div className="program-console-tab-buttons">
            <button type="button" className={tab === 'simulate' ? 'active' : ''} onClick={() => setTab('simulate')}>隔离模拟</button>
            <button type="button" className={tab === 'runtime' ? 'active' : ''} onClick={() => setTab('runtime')}>运行轨迹</button>
          </div>
          <div className="program-console-status">
            <span>{status?.status ?? '尚未执行'}{status?.task ? ` · ${status.task}` : ''}{status?.reason ? ` · ${status.reason}` : ''}</span>
          </div>
          <button type="button" className="program-debug-close" aria-label="关闭调试面板" title="关闭调试面板" onClick={() => setDebugOpen(false)}>
            <X size={15}/>
          </button>
        </div>
        <div className="program-console-body nowheel nopan nodrag" onWheel={e => e.stopPropagation()}>
          {validation && <div className={`program-diagnostics ${validation.valid ? 'valid' : ''}`}>{validation.valid ? '程序校验通过' : validation.diagnostics.map((d,index) => {
            const g = d.graph === 'main' ? doc : doc.subgraphs.find(s => s.id === d.graph)
            const target = g?.nodes.find(n => n.id === d.node)
            const targetSpec = target ? definition(target, doc, catalog, g ?? graph) : undefined
            const DiagIcon = target ? getCardIcon(target.type, targetSpec?.category) : undefined
            const targetTitle = target ? `${targetSpec?.label ?? target.type}${target.label ? `（${target.label}）` : ''}` : d.node
            return <button key={index} onClick={() => {setGraphId(d.graph); setSelection(d.node ? [d.node] : [])}}>{DiagIcon && <DiagIcon size={13} style={{color:targetSpec ? categoryColor(targetSpec.category) : undefined, flexShrink:0}} aria-hidden="true"/>}{d.message}{targetTitle ? ` · ${targetTitle}` : ''}</button>
          })}</div>}
          {tab === 'simulate' && <>
            <div className="program-sim-actions">
              <button type="button" className="button secondary" disabled={busy} onClick={() => void simulate(Math.min(simSteps+1,1000))}><StepForward size={14}/>单步</button>
              <button type="button" className="button primary" disabled={busy} onClick={() => void simulate(100)}><Play size={14}/>模拟运行</button>
            </div>
            <details className="program-sim-params">
              <summary>
                <span>环境与资源数据</span>
                <small>（时间、资源等参数，点击展开修改）</small>
              </summary>
              <div className="program-sim-params-content">
                <label>模拟时间<input type="datetime-local" value={simTime} onChange={e => {setSimTime(e.target.value); setSimSteps(0)}}/></label>
                {/* 数字输入框聚焦时滚轮会直接改数值，onWheel 先把输入框失焦，滚动面板才安全 */}
                {catalog.resources.map(r => <label key={r.name}>{r.name.startsWith('Emotion') ? `舰队 ${r.name.slice(-1)} 心情` : ui(`resource.${r.name}` as UiKey)}<input type="number" placeholder="数据不可用" value={resources[r.name] ?? ''} onWheel={e => (e.target as HTMLInputElement).blur()} onChange={e => {setResources({...resources,[r.name]:e.target.value}); setSimSteps(0)}}/></label>)}
                <label>含体力箱的总行动力<input type="number" value={apTotal} onWheel={e => (e.target as HTMLInputElement).blur()} onChange={e => {setApTotal(e.target.value); setSimSteps(0)}}/></label>
                <label>任务结果序列<input value={outcomes} onChange={e => {setOutcomes(e.target.value); setSimSteps(0)}} placeholder="completed,yielded,failed"/></label>
              </div>
            </details>
          </>}
          <details className="program-sim-tasks-details"><summary>模拟任务状态</summary><JsonField label="任务列表（名称、启用状态、下次运行时间）" value={simTasks} onChange={value => {if (Array.isArray(value)) {setSimTasks(value); setSimSteps(0)}}}/></details><div className="program-trace">{status?.trace?.length ? status.trace.map((line,index) => {
            const cardDef = catalog.cards.find(c => c.type === line.type)
            const TraceIcon = getCardIcon(line.type, cardDef?.category)
            const sub = line.graph && line.graph !== 'main' ? doc.subgraphs.find(s => s.id === line.graph) : undefined
            const orig = cardDef?.label ?? sub?.name ?? line.type ?? line.node
            const displayLabel = line.label ? `${orig}（${line.label}） · ${line.type}` : `${orig} · ${line.type}`
            return <div key={index}><span>{index + 1}</span><button onClick={() => {setGraphId(String(line.graph ?? 'main')); setSelection([String(line.node)])}}><TraceIcon size={12} style={{color:categoryColor(cardDef?.category ?? ''), flexShrink:0}} aria-hidden="true"/>{displayLabel}</button><code>{JSON.stringify(line.input ?? line.value ?? line.output ?? line.exit ?? '')}</code></div>
          }) : <p className="muted">模拟不会连接设备，也不会修改资源或持久变量。执行后可查看每张卡片的输入、出口和结果。</p>}</div>
        </div>
      </aside>
    </div>
  </div>
}

/** 调度程序页入口：react-flow 的 hook 必须在 Provider 内使用，Editor 由这里统一包一层。 */
export function SchedulerProgram() {return <ReactFlowProvider><Editor/></ReactFlowProvider>}
