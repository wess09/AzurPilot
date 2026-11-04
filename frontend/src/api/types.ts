/**
 * @fileoverview 后端 WebSocket API 接口与数据模型类型定义。
 */

import type {Catalog, ProgramSaved, ProgramSimulation, ProgramValidation, RuntimeProgramState} from '../scheduler/types'
import type {MindCatalog, MindShip} from '../mind/types'
import type {Catalog as FleetTechCatalog, Report as FleetTechReport} from '../fleet-tech/types'

export type Scalar = string | number | boolean | null
export type Value = Scalar | Value[] | {[key: string]: Value}
type Values = Record<string, Record<string, Record<string, Value>>>
export type Status = 'running' | 'stopped' | 'error' | 'updating'
export interface Instance { name: string; status: Status; serial: string; server: string; region?: 'cn' | 'en' | 'jp' | 'tw' | null; currentTask?: string | null }
export interface UpdateStatus {
  state: string; localHead: string | null; upstreamHead: string | null; branch: string
  ahead: number; behind: number; available: boolean; busy: boolean; canApply: boolean; canCancel: boolean; error: string
  /** 本地与更新源历史互不包含（例如镜像重写历史导致 SHA 分离），更新前需弹窗确认。 */
  shaMismatch?: boolean
  managedByAndroid?: boolean
}
interface Commit { sha: string; author: string; date: string; message: string }
export interface CommitHistory { entries: Commit[]; total: number; hasMore: boolean; localHead: string | null; upstreamHead: string | null }
export interface Field { type: string; value: Value; valuetype?: string; mode?: string; display?: string; option?: Value[]; validate?: string | number[]; preserve_empty?: boolean }
/** 侧栏内容检索的一条命中：要么是任务名，要么是某个配置项。 */
export interface SearchContentHit {
  task: string
  key: string
  label: string
  help: string
  values: string
}

export interface SearchContentResult {
  tasks: SearchContentHit[]
  groups: SearchContentHit[]
  options: SearchContentHit[]
}

export interface Schema {
  menu: Record<string, { menu: string; page: string; tasks: string[] }>
  args: Record<string, Record<string, Record<string, Field>>>
  translations: Record<string, unknown>
}
export interface Config { instance: string; revision: string; values: Values; options?: Record<string, Value[]> }
export interface OpsiSimulatorResult {
  cl1Count: number; meowCount: number; crashedProbability: number
  cl1Time: number; meowTime: number; ap: number; coin: number
}
export interface OpsiSimulatorStatus {
  instance: string; state: 'idle' | 'running' | 'stopping' | 'completed' | 'interrupted' | 'failed'
  running: boolean; completedSamples: number; totalSamples: number; error: string
  runId: number
  result: OpsiSimulatorResult | null; figure: string | null; logs: Logs
}
interface ScheduledTask { name: string; nextRun: string; pending: boolean; state: 'running' | 'pending' | 'waiting' }
export interface Resource { name: string; label: string; value: number | null; limit?: number; total?: number | null; record?: string }
export interface Overview {
  instance: string; revision: string; status: Status; tasks: ScheduledTask[]
  resources: Resource[]; emulator: Record<string, Value>
}
export interface LogEntry { id: number; level: string; text: string }
export interface Logs { instance: string; cursor: number; reset: boolean; entries: LogEntry[] }
export interface Preview { instance: string; image: string | null; capturedAt: string | null }
export interface Statistics { instance: string; resource: string; points: {time: string; value: number}[]; truncated: boolean }
export interface StatPoint {time: string; value: number; source?: string}
export interface StatSeries {key: string; label: string; icon?: string; points: StatPoint[]}
export interface StatPointCompact {t: number; v: number; s?: string}
export interface StatSeriesCompact {key: string; label: string; icon?: string; points: StatPointCompact[]}
/** 数值按顺序对应报表的共用时间轴。 */
export interface StatSeriesColumn {key: string; label: string; icon?: string; values: number[]; sources?: string[]}
export type StatSeriesWire = StatSeriesCompact | StatSeriesColumn
export interface StatTable {title: string; columns: string[]; rows: Scalar[][]; note?: string; defaultSort?: TableSort}
export interface TableSort {index: number; descending: boolean}
export interface StatisticsReport {
  instance: string; category: string; month: string
  /** 图标名称（可选）：为卡片单独指定图标（科研物品填 'research:<模板名>'，大世界掉落填 'opsi:<模板名>'），缺省按 label 查内置表。 */
  metrics: {label: string; value: number | null; unit: string; icon?: string}[]
  series: StatSeries[]; tables: StatTable[]; notes: string[]
  /** 大世界掉落专用：任务筛选选项（含当前时间窗口内没有记录的任务），count 表示窗口内掉落记录数。 */
  taskOptions?: {key: string; label: string; count: number}[]
  /** 本次出现的物品名、任务名的译名：{中文名: {语言: 名称}}；固定文案由前端翻译。 */
  glossary?: StatGlossary
}
/** 统计接口附带的名称对照：{中文名: {语言: 名称}}。 */
export type StatGlossary = Record<string, Partial<Record<string, string>>>

export interface StatisticsReportWire extends Omit<StatisticsReport, 'series'> {
  /** 共用时间轴（微秒整数）。 */
  axis?: number[]
  series: StatSeriesWire[]
}
/** 指挥喵评分的单条天赋。`kind` 为 `special`（彩天赋）时高亮，`inferred` 表示这条由识别推断而来。 */
export interface MeowfficerTalent { name: string; level?: number; kind?: string; inferred?: boolean }
/** 指挥喵评分的一条评分口径；`x`/`y` 是两个维度的命中数（加权点制的口径为 null），`primary` 是主口径。 */
export interface MeowfficerRubric {
  key?: string; label: string; tier?: string; score?: number
  x?: number | null; y?: number | null
  xLabel?: string; yLabel?: string
  xHits?: string[]; yHits?: string[]; notes?: string[]; source?: string; primary?: boolean
}
/** 洗点推荐：verdict 决定配色，文案由后端给出（口径/成本也一并算好）。 */
export interface MeowfficerAdvice {
  verdict: string; headline: string; reason: string
  label?: string; score?: number; tier?: string
  cost?: number | null; costEstimated?: boolean; pointsSpent?: number; costText?: string
  targets?: string[]
}
/** 指挥喵评分里的一只猫。 */
export interface MeowfficerCat {
  source?: string; cat: string; tags?: string[]; fixed?: boolean; note?: string; maxed?: boolean
  level?: number | null
  pointsSpent?: number; primary?: string; talents?: MeowfficerTalent[]; rubrics?: MeowfficerRubric[]
  advice?: MeowfficerAdvice | null
}
/** 「指挥喵评分」任务写入 log/meowfficer_score.json 的结构化结果，报告不存在时后端返回 NOT_FOUND。 */
export interface MeowfficerScoreReport { instance: string; generatedAt: string; count: number; cats: MeowfficerCat[] }
interface DeployField { key: string; type: string; label: string; help: string; value: Value; options: Value[] }
interface RemoteAccessStatus { enabled: boolean; state: string; address: string; error: string }
export interface Settings { groups: {key: string; label: string; fields: DeployField[]}[]; notice: string; demo: boolean; remote?: RemoteAccessStatus }
export interface RemotePairing { id: string; client_id: string; code: string; particle_secret: string; expires_at: number }
export interface RemoteClient { id: string; created_at: number }
export interface ApiEvent { v: 1; type: 'event'; topic: string; seq: number; data: unknown }
export interface ApiResponse { v: 1; type: 'response'; id: string; ok: boolean; result?: unknown; error?: {code: string; message: string; details?: unknown} }
export interface Announcement {
  announcementId: string
  title: string
  content: string
  url?: string
}
/** 背景图库条目：文件都放在服务器的 cache/background/library 下。 */
export interface BackgroundGalleryEntry {
  id: string
  name: string
  size: number
  added: number
  kind: 'image' | 'video'
  source?: string
}

export interface LauncherCommand {
  id: string; status: 'pending' | 'succeeded' | 'failed' | 'expired'; deadline: number
  result?: {supported: boolean; enabled: boolean | null}; error?: {code: string; message: string}
}
export interface LauncherStatus {
  connected: boolean; platform: string; version: string; capabilities: string[]
  autostart: {supported: boolean; enabled: boolean | null}; commands: LauncherCommand[]
}

export interface DockCard {
  full_star?: boolean | null; form?: 'base' | 'retrofit' | null
  id: number; group_type: number | null; name: string; level: number
  rarity: string; base_rarity: string; extra_exp: number | null; review: boolean; source: string
}

export interface LedgerDifference {
  id: string; kind: 'ship' | 'technology' | 'nation'; operation: 'add' | 'update' | 'remove' | 'resolve'
  ship_id: number | null; group_type: number | null; name: string
  before: Record<string, unknown> | null; after: Record<string, unknown> | null; fields: string[]
  candidates: {id: number; name: string; level: number}[]
}

export interface DockReport {
  pending_read?: {source: string; updated_at: string; observed_count: number; review_count: number; complete: boolean}
  pending_revision: string | null; pending_changes: LedgerDifference[]
  legacy_imported?: boolean
  scan_range?: {min_level: number; max_level: number}
  instance: string; revision: string; updated_at: string | null; min_level: number; max_level: number
  ships: DockCard[]; complete: boolean; review_count: number; source: string
}

export interface Results {
  'dock.report': DockReport
  'dock.configure': DockReport
  'dock.importLegacy': DockReport
  'dock.patch': DockReport
  'dock.review': DockReport
  'dock.stageImport': DockReport
  'launcher.status': LauncherStatus
  'launcher.autostart.set': {commandId: string; status: 'pending'}
  'launcher.command.get': LauncherCommand
  'auth.launcher': {authenticated: boolean}
  'mind.catalog': MindCatalog
  'fleetTech.catalog': FleetTechCatalog
  'fleetTech.report': FleetTechReport
  'fleetTech.patch': FleetTechReport
  'fleetTech.mergeShips': FleetTechReport
  'mind.plan': import('../mind/cultivation').CultivationReport
  'mind.import': {ships: MindShip[]}
  'mind.recognize': {ships: MindShip[]}
  'statistics.resourceFlows': ResourceFlowReport
  'stock.status': StockExchangeStatus
  'stock.rebuild': StockExchangeRebuild
  'stock.register': StockExchangeStatus
  'opsi.simulator.status': OpsiSimulatorStatus
  'opsi.simulator.start': OpsiSimulatorStatus
  'opsi.simulator.stop': OpsiSimulatorStatus
  'opsi.simulator.figure': {instance: string; image: string | null}
  'config.export': Values & {_schedulerProgram?: Pick<ProgramSaved, 'mode' | 'draft' | 'active'>}
  'background.access': {token: string}
  'scheduler.program.catalog': Catalog
  'scheduler.program.get': ProgramSaved
  'scheduler.program.save': ProgramSaved
  'scheduler.program.apply': ProgramSaved
  'scheduler.program.validate': ProgramValidation
  'scheduler.program.simulate': ProgramSimulation
  'scheduler.program.state': RuntimeProgramState
  'accounts.status': AccountStatus
  'accounts.manage': AccountStatus
  'announcement.get': Announcement | null
  'background.resolve': {final_url: string; content_type: string}
  'background.gallery.list': BackgroundGalleryEntry[]
  'background.gallery.add': {entry: BackgroundGalleryEntry}
  'background.gallery.remove': {removed: boolean}
  'background.gallery.open': {path: string}
  'updater.status': UpdateStatus
  'updater.commits': CommitHistory
  'updater.fetch': {accepted: boolean}
  'updater.apply': {accepted: boolean}
  'updater.cancel': {accepted: boolean}
  'system.ping': {pong: boolean}
  'auth.login': {authenticated: boolean}
  'events.subscribe': {topics: string[]; instance: string | null}
  'schema.get': Schema
  'search.content': SearchContentResult
  'instances.list': Instance[]
  'instances.create': Config
  'instances.importable': Array<{name: string; modified: number}>
  'instances.importConfig': {name: string}
  'instances.delete': {deleted: string}
  'config.get': Config
  'config.patch': Config
  'fleetTraining.reset': Config
  'overview.get': Overview
  'scheduler.start': Overview
  'scheduler.stop': Overview
  'tasks.run': Overview
  'logs.get': Logs
  'preview.capture': Preview
  'statistics.resources': Statistics
  'statistics.report': StatisticsReportWire
  'statistics.refreshLoot': {refreshed: boolean}
  'meowfficer.scoreReport': MeowfficerScoreReport
  'meowfficer.clearReport': {cleared: boolean; removed: string[]}
  'settings.get': Settings
    'remote.pair.create': RemotePairing
    'remote.pair.status': {state: 'pending' | 'claimed' | 'expired'}
    'remote.clients': RemoteClient[]
    'remote.revoke': {revoked: boolean}
  'settings.patch': {updated: string[]}
  'startup.get': {enabled: boolean; remember: boolean}
  'startup.set': {enabled: boolean; remember: boolean}
}

export interface ResourceFlowEntry {
  id: number; ts: string; resource: string; amount: number; task: string; operation: string
  evidence: 'confirmed' | 'recognition' | 'observed' | 'adjustment'; run_id: string | null
}
export interface ResourceFlowReport {
  instance: string; start: string; end: string; offset: number; limit: number; total: number; throughId: number
  resources: {key: string; label: string; group: string; current: number | null; observedAt: string | null; income: number; expense: number; adjustment: number; count: number}[]
  tasks: string[]
  flows: {resource: string; task: string; operation: string; evidence: ResourceFlowEntry['evidence']; income: number; expense: number; count: number}[]
  entries: ResourceFlowEntry[]
  oilControl: {enable: boolean; target: number}
  /** 物品名的译名：{中文名: {语言: 名称}}。 */
  glossary?: StatGlossary
}

export interface StockExchangeStatus {url:string;instance:string;instanceId:string;registered:boolean;deleted?:boolean;bound:boolean;stock:{id:number;symbol:string;name:string;price:number;observedAt:number;bound:boolean}|null;bindingCode:string;message:string;lastObservedAt:number}
export interface StockExchangeRebuild {instance:string;scope:'instance'|'all';affectedInstances:string[];rebuilt:boolean}

export interface AccountStatus {
  destroyed?: boolean
  local_bound?: boolean
  tpm_available?: boolean
  initialized: boolean; enabled: boolean; unlocked: boolean; tpm_bound: boolean
  profiles?: Array<{id: string; label: string; users: Array<{uid: string; name: string}>}>
  selected?: string | null
}
