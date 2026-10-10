// 由 dev_tools.export_api_schema 生成，请勿手动编辑。
export interface Parameters {
  "system.ping": Record<string, never>
  "schema.get": { language?: "zh-CN" | "zh-MIAO" | "en-US" | "ja-JP" | "zh-TW" }
  "search.content": { query: string }
  "instances.list": Record<string, never>
  "instances.create": { name: string; source?: string | null; import_file?: string | null }
  "instances.importable": Record<string, never>
  "instances.importConfig": { name: string; content: string }
  "instances.delete": { instance: string; revision: string }
  "config.get": { instance: string }
  "config.export": { instance: string }
  "config.patch": { instance: string; revision?: string | null; changes: Array<{ path: string; value: unknown }> }
  "overview.get": { instance: string }
  "mind.catalog": { instance: string }
  "mind.report": { instance: string }
  "mind.calculate": { instance: string; ships: Array<{ name: string; level: number; rarity?: "" | "N" | "R" | "SR" | "SSR" | "UR"; base_rarity?: "" | "N" | "R" | "SR" | "SSR" | "UR"; excluded?: boolean; review?: boolean; source?: string }> }
  "mind.save": { instance: string; ships: Array<{ name: string; level: number; rarity?: "" | "N" | "R" | "SR" | "SSR" | "UR"; base_rarity?: "" | "N" | "R" | "SR" | "SSR" | "UR"; excluded?: boolean; review?: boolean; source?: string }>; revision: string }
  "mind.import": { instance: string; filename: string; content: string }
  "mind.recognize": { instance: string; filename: string; content: string }
  "mind.export": { instance: string; format?: "json" | "csv" | "xlsx" }
  "stock.status": { instance: string }
  "stock.rebuild": { instance: string; confirm?: boolean; scope?: "instance" | "all" }
  "stock.request": { instance: string; path: string; method?: "GET" | "POST" | "DELETE"; body?: Record<string, unknown> | null; etag?: string }
  "scheduler.start": { instance: string }
  "scheduler.stop": { instance: string }
  "scheduler.program.catalog": { instance: string }
  "scheduler.program.get": { instance: string }
  "scheduler.program.save": { instance: string; document: { entry: string; nodes: Array<{ id: string; type: string; label?: string; comment?: string; params?: Record<string, unknown>; position?: Record<string, unknown> }>; edges?: Array<{ id: string; source: string; sourcePort: string; target: string; targetPort?: string; kind?: "control" | "data" }>; schemaVersion?: number; name?: string; subgraphs?: Array<{ entry: string; nodes: Array<{ id: string; type: string; label?: string; comment?: string; params?: Record<string, unknown>; position?: Record<string, unknown> }>; edges?: Array<{ id: string; source: string; sourcePort: string; target: string; targetPort?: string; kind?: "control" | "data" }>; id: string; name: string; pure?: boolean; inputs?: Array<{ name: string; type?: "any" | "number" | "boolean" | "string" | "time" | "duration" | "resource" | "task" | "tasks" | "result" | "list" | "object"; required?: boolean }>; outputs?: Array<{ name: string; type?: "any" | "number" | "boolean" | "string" | "time" | "duration" | "resource" | "task" | "tasks" | "result" | "list" | "object"; required?: boolean }> }>; variables?: Array<{ name: string; type?: "any" | "number" | "boolean" | "string" | "time" | "duration" | "resource" | "task" | "tasks" | "result" | "list" | "object"; initial?: unknown; persistent?: boolean }>; viewport?: Record<string, unknown> }; revision: string }
  "scheduler.program.validate": { instance: string; document: { entry: string; nodes: Array<{ id: string; type: string; label?: string; comment?: string; params?: Record<string, unknown>; position?: Record<string, unknown> }>; edges?: Array<{ id: string; source: string; sourcePort: string; target: string; targetPort?: string; kind?: "control" | "data" }>; schemaVersion?: number; name?: string; subgraphs?: Array<{ entry: string; nodes: Array<{ id: string; type: string; label?: string; comment?: string; params?: Record<string, unknown>; position?: Record<string, unknown> }>; edges?: Array<{ id: string; source: string; sourcePort: string; target: string; targetPort?: string; kind?: "control" | "data" }>; id: string; name: string; pure?: boolean; inputs?: Array<{ name: string; type?: "any" | "number" | "boolean" | "string" | "time" | "duration" | "resource" | "task" | "tasks" | "result" | "list" | "object"; required?: boolean }>; outputs?: Array<{ name: string; type?: "any" | "number" | "boolean" | "string" | "time" | "duration" | "resource" | "task" | "tasks" | "result" | "list" | "object"; required?: boolean }> }>; variables?: Array<{ name: string; type?: "any" | "number" | "boolean" | "string" | "time" | "duration" | "resource" | "task" | "tasks" | "result" | "list" | "object"; initial?: unknown; persistent?: boolean }>; viewport?: Record<string, unknown> }; mode?: "native" | "enhance" | "takeover" }
  "scheduler.program.simulate": { instance: string; document: { entry: string; nodes: Array<{ id: string; type: string; label?: string; comment?: string; params?: Record<string, unknown>; position?: Record<string, unknown> }>; edges?: Array<{ id: string; source: string; sourcePort: string; target: string; targetPort?: string; kind?: "control" | "data" }>; schemaVersion?: number; name?: string; subgraphs?: Array<{ entry: string; nodes: Array<{ id: string; type: string; label?: string; comment?: string; params?: Record<string, unknown>; position?: Record<string, unknown> }>; edges?: Array<{ id: string; source: string; sourcePort: string; target: string; targetPort?: string; kind?: "control" | "data" }>; id: string; name: string; pure?: boolean; inputs?: Array<{ name: string; type?: "any" | "number" | "boolean" | "string" | "time" | "duration" | "resource" | "task" | "tasks" | "result" | "list" | "object"; required?: boolean }>; outputs?: Array<{ name: string; type?: "any" | "number" | "boolean" | "string" | "time" | "duration" | "resource" | "task" | "tasks" | "result" | "list" | "object"; required?: boolean }> }>; variables?: Array<{ name: string; type?: "any" | "number" | "boolean" | "string" | "time" | "duration" | "resource" | "task" | "tasks" | "result" | "list" | "object"; initial?: unknown; persistent?: boolean }>; viewport?: Record<string, unknown> }; mode?: "native" | "enhance" | "takeover"; context?: Record<string, unknown>; outcomes?: Array<"completed" | "yielded" | "recoverable" | "failed">; steps?: number }
  "scheduler.program.apply": { instance: string; revision: string; mode: "native" | "enhance" | "takeover" }
  "scheduler.program.state": { instance: string }
  "tasks.run": { instance: string; task: string }
  "logs.get": { instance: string; after?: number }
  "opsi.simulator.status": { instance: string; after?: number }
  "opsi.simulator.start": { instance: string }
  "opsi.simulator.stop": { instance: string }
  "opsi.simulator.figure": { instance: string }
  "preview.capture": { instance: string }
  "statistics.refreshLoot": { instance: string }
  "statistics.report": { instance: string; category?: "resources" | "action" | "opsi" | "commission" | "ships" | "loot" | "research" | "storage"; month?: string | null; days?: number; period?: "day" | "week" | "month"; series?: number; scope?: "series" | "consumable"; task?: string | null; include_series?: boolean }
  "statistics.resourceFlows": { instance: string; days?: number; start?: string | null; end?: string | null; resource?: string | null; task?: string | null; offset?: number; limit?: number; through_id?: number | null }
  "meowfficer.scoreReport": { instance: string; limit?: number }
  "meowfficer.clearReport": { instance: string }
  "statistics.resources": { instance: string; days?: number; resource?: "Oil" | "Coin" | "Gem" | "Cube" | "Pt" | "ActionPoint" | "Core" | "Medal" | "Merit" | "GuildCoin" | "YellowCoin" | "PurpleCoin" }
  "settings.get": Record<string, never>
  "settings.patch": { values: Record<string, unknown> }
  "startup.get": { instance: string }
  "startup.set": { instance: string; enabled?: boolean | null; remember?: boolean | null }
  "accounts.status": { instance: string }
  "accounts.manage": { instance: string; action: "create" | "unlock" | "lock" | "list" | "capture" | "select" | "enable" | "password" | "delete" | "bind_tpm" | "unbind_tpm" | "bind_local" | "unbind_local"; password?: string; new_password?: string; label?: string; profile?: string; enabled?: boolean }
  "updater.status": Record<string, never>
  "updater.commits": { offset?: number; limit?: number }
  "updater.fetch": Record<string, never>
  "updater.apply": Record<string, never>
  "updater.cancel": Record<string, never>
  "announcement.get": { force?: boolean }
  "background.access": Record<string, never>
  "background.resolve": { url: string }
  "background.gallery.list": Record<string, never>
  "background.gallery.add": { url: string; name?: string }
  "background.gallery.remove": { id: string }
  "background.gallery.open": Record<string, never>
  "auth.login": { password?: string }
  "events.subscribe": { instance?: string | null; topics: Array<"instances" | "overview" | "logs" | "preview" | "stock"> }
}
export interface SchedulerModels {
  ProgramDocument: { entry: string; nodes: Array<{ id: string; type: string; label?: string; comment?: string; params?: Record<string, unknown>; position?: Record<string, unknown> }>; edges?: Array<{ id: string; source: string; sourcePort: string; target: string; targetPort?: string; kind?: "control" | "data" }>; schemaVersion?: number; name?: string; subgraphs?: Array<{ entry: string; nodes: Array<{ id: string; type: string; label?: string; comment?: string; params?: Record<string, unknown>; position?: Record<string, unknown> }>; edges?: Array<{ id: string; source: string; sourcePort: string; target: string; targetPort?: string; kind?: "control" | "data" }>; id: string; name: string; pure?: boolean; inputs?: Array<{ name: string; type?: "any" | "number" | "boolean" | "string" | "time" | "duration" | "resource" | "task" | "tasks" | "result" | "list" | "object"; required?: boolean }>; outputs?: Array<{ name: string; type?: "any" | "number" | "boolean" | "string" | "time" | "duration" | "resource" | "task" | "tasks" | "result" | "list" | "object"; required?: boolean }> }>; variables?: Array<{ name: string; type?: "any" | "number" | "boolean" | "string" | "time" | "duration" | "resource" | "task" | "tasks" | "result" | "list" | "object"; initial?: unknown; persistent?: boolean }>; viewport?: Record<string, unknown> }
  CardDefinition: { type: string; label: string; category: string; pure?: boolean; entry?: boolean; inputs?: Array<{ name: string; type?: "any" | "number" | "boolean" | "string" | "time" | "duration" | "resource" | "task" | "tasks" | "result" | "list" | "object"; required?: boolean }>; outputs?: Array<{ name: string; type?: "any" | "number" | "boolean" | "string" | "time" | "duration" | "resource" | "task" | "tasks" | "result" | "list" | "object"; required?: boolean }>; exits?: Array<string>; params?: Record<string, unknown> }
  PortDefinition: { name: string; type?: "any" | "number" | "boolean" | "string" | "time" | "duration" | "resource" | "task" | "tasks" | "result" | "list" | "object"; required?: boolean }
  ResourceObservation: { name: string; value?: number | number | null; limit?: number | number | null; total?: number | number | null; observedAt?: string | null; source?: string; status?: "fresh" | "stale" | "missing" | "unavailable"; refreshable?: boolean }
  TaskInvocation: { task: string; node: string; overrides?: Record<string, unknown> }
  TaskOutcome: { task: string; status: "completed" | "yielded" | "recoverable" | "failed" | "interrupted"; reason?: string; finishedAt?: string | null }
  ProgramState: { status?: string; node?: string | null; reason?: string; task?: string | null; deadline?: string | null; trace?: Array<Record<string, unknown>>; variables?: Record<string, unknown>; resources?: Record<string, unknown> }
}
