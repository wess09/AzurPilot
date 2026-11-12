/**
 * @fileoverview 调度器卡片程序的类型模型；运行态结构沿用后端生成的契约。
 */
import type {SchedulerModels} from '../api/generated'

/** 调度模式：native 用原调度，enhance 增强调度，takeover 由卡片程序完全接管。 */
export type ProgramMode = 'native' | 'enhance' | 'takeover'
export type PortType = 'any' | 'number' | 'boolean' | 'string' | 'time' | 'duration' | 'resource' | 'task' | 'tasks' | 'result' | 'list' | 'object'
interface Port {name: string; type: PortType; required: boolean}
export interface ProgramNode {id: string; type: string; label: string; comment?: string; params: Record<string, unknown>; position: {x: number; y: number}}
interface ProgramEdge {id: string; source: string; sourcePort: string; target: string; targetPort: string; kind: 'control' | 'data'}
export interface Graph {entry: string; nodes: ProgramNode[]; edges: ProgramEdge[]}
/** 封装的子图：pure 表示数据组合（只有数据端口），否则为执行组合（要求单一控制入口、出口汇合）。 */
export interface Subgraph extends Graph {id: string; name: string; pure: boolean; inputs: Port[]; outputs: Port[]}
export interface ProgramDocument extends Graph {
  schemaVersion: 1; name: string; subgraphs: Subgraph[]
  variables: Array<{name: string; type: PortType; initial: unknown; persistent: boolean}>
  viewport: {x: number; y: number; zoom: number}
}
export interface CardDefinition {type: string; label: string; category: string; pure: boolean; entry?: boolean; inputs: Port[]; outputs: Port[]; exits: string[]; params: Record<string, unknown>}
export interface Catalog {
  cards: CardDefinition[]; builtins: Subgraph[]; templates: Record<'takeover' | 'enhance' | 'all', ProgramDocument>
  tasks: Array<{name: string; command: string; enabled: boolean; nextRun: string}>
  resources: Array<{name: string; label: string; refreshable: boolean}>
  overrides: Record<string, string | string[]>
}
/** 服务端保存态：draft 为草稿文档，revision 用作保存与应用的乐观锁。 */
export interface ProgramSaved {mode: ProgramMode; draft: ProgramDocument; active: ProgramDocument | null; revision: string; generation: number}
interface ProgramDiagnostic {message: string; node?: string | null; graph: string}
export interface ProgramValidation {valid: boolean; diagnostics: ProgramDiagnostic[]}
export type ProgramState = Required<Pick<SchedulerModels['ProgramState'], 'status' | 'trace'>> & SchedulerModels['ProgramState']
export interface ProgramSimulation extends ProgramValidation {state: ProgramState; effects: Array<Record<string, unknown>>; persistent?: Record<string, unknown>}
export interface RuntimeProgramState {mode: ProgramMode; generation: number; state: ProgramState}
