export type Scalar = string | number | boolean | null
export type Value = Scalar | Value[] | {[key: string]: Value}
export type Values = Record<string, Record<string, Record<string, Value>>>
export type Status = 'running' | 'stopped' | 'error' | 'updating'
export interface Instance { name: string; status: Status; serial: string; server: string; currentTask?: string | null }
export interface UpdateStatus {
  state: string; localHead: string | null; upstreamHead: string | null; branch: string
  ahead: number; behind: number; available: boolean; busy: boolean; canApply: boolean; canCancel: boolean; error: string
  /* 本地与更新源历史互不包含（例如镜像重写历史导致 SHA 分离），更新前需弹窗确认 */
  shaMismatch?: boolean
  managedByAndroid?: boolean
}
export interface Commit { sha: string; author: string; date: string; message: string }
export interface CommitHistory { entries: Commit[]; total: number; hasMore: boolean; localHead: string | null; upstreamHead: string | null }
export interface Field { type: string; value: Value; mode?: string; display?: string; option?: Value[]; validate?: string | number[]; preserve_empty?: boolean }
export interface Schema {
  menu: Record<string, { menu: string; page: string; tasks: string[] }>
  args: Record<string, Record<string, Record<string, Field>>>
  translations: Record<string, unknown>
}
export interface Config { instance: string; revision: string; values: Values }
export interface ScheduledTask { name: string; nextRun: string; pending: boolean; state: 'running' | 'pending' | 'waiting' }
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
export interface StatSeries {key: string; label: string; points: StatPoint[]}
export interface StatTable {title: string; columns: string[]; rows: Scalar[][]; note?: string; defaultSort?: TableSort}
export interface TableSort {index: number; descending: boolean}
export interface StatisticsReport {
  instance: string; category: string; month: string
  /* icon 可选：给卡片单独指定图标（科研物品写 'research:<模板名>'，大世界掉落写 'opsi:<模板名>'），缺省按 label 查内置表 */
  metrics: {label: string; value: number | null; unit: string; icon?: string}[]
  series: StatSeries[]; tables: StatTable[]; notes: string[]
  /* 大世界掉落专用：任务筛选的选项（含当前窗口内没有记录的任务），count 是窗口内掉落记录数 */
  taskOptions?: {key: string; label: string; count: number}[]
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
export interface DeployField { key: string; type: string; label: string; help: string; value: Value; options: Value[] }
export interface RemoteAccessStatus { enabled: boolean; state: string; address: string; error: string }
export interface Settings { groups: {key: string; label: string; fields: DeployField[]}[]; notice: string; demo: boolean; remote?: RemoteAccessStatus }
export interface ApiEvent { v: 1; type: 'event'; topic: string; seq: number; data: unknown }
export interface ApiResponse { v: 1; type: 'response'; id: string; ok: boolean; result?: unknown; error?: {code: string; message: string; details?: unknown} }
export interface ScriptDiagnostic { code?: string; message: string; line?: number | null; column?: number | null; severity?: 'error' | 'warning' }
export interface ShopStrategyValidation { valid: boolean; diagnostics: ScriptDiagnostic[]; summary?: string }
export type ShopStrategyTask = 'EventShop' | 'ShopFrequent' | 'ShopOnce' | 'PrivateQuarters' | 'OpsiShop' | 'OpsiVoucher'
export interface Announcement {
  announcementId: string
  title: string
  content: string
  url?: string
}
export interface Results {
  'accounts.status': AccountStatus
  'accounts.manage': AccountStatus
  'announcement.get': Announcement | null
  'updater.status': UpdateStatus
  'updater.commits': CommitHistory
  'updater.fetch': {accepted: boolean}
  'updater.apply': {accepted: boolean}
  'updater.cancel': {accepted: boolean}
  'system.ping': {pong: boolean}
  'auth.login': {authenticated: boolean}
  'events.subscribe': {topics: string[]; instance: string | null}
  'schema.get': Schema
  'instances.list': Instance[]
  'instances.create': Config
  'instances.importable': Array<{name: string; modified: number}>
  'instances.importConfig': {name: string}
  'instances.delete': {deleted: string}
  'config.get': Config
  'config.patch': Config
  'shop_strategy.validate': ShopStrategyValidation
  'overview.get': Overview
  'scheduler.start': Overview
  'scheduler.stop': Overview
  'tasks.run': Overview
  'logs.get': Logs
  'preview.capture': Preview
  'statistics.resources': Statistics
  'statistics.report': StatisticsReport
  'statistics.refreshLoot': {refreshed: boolean}
  'meowfficer.scoreReport': MeowfficerScoreReport
  'meowfficer.clearReport': {cleared: boolean; removed: string[]}
  'settings.get': Settings
  'settings.patch': {updated: string[]}
  'startup.get': {enabled: boolean; remember: boolean}
  'startup.set': {enabled: boolean; remember: boolean}
}

export interface AccountStatus {
  destroyed?: boolean
  local_bound?: boolean
  tpm_available?: boolean
  initialized: boolean; enabled: boolean; unlocked: boolean; tpm_bound: boolean
  profiles?: Array<{id: string; label: string; users: Array<{uid: string; name: string}>}>
  selected?: string | null
}
