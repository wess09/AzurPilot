// 由 dev_tools.export_api_schema 生成，请勿手动编辑。
export interface Parameters {
  "system.ping": Record<string, never>
  "schema.get": { language?: "zh-CN" | "zh-MIAO" | "en-US" | "ja-JP" | "zh-TW" }
  "instances.list": Record<string, never>
  "instances.create": { name: string; source?: string | null; import_file?: string | null }
  "instances.importable": Record<string, never>
  "instances.importConfig": { name: string; content: string }
  "instances.delete": { instance: string; revision: string }
  "config.get": { instance: string }
  "config.patch": { instance: string; revision?: string | null; changes: Array<{ path: string; value: unknown }> }
  "shop_strategy.validate": { instance: string; task: "EventShop" | "ShopFrequent" | "ShopOnce" | "PrivateQuarters" | "OpsiShop" | "OpsiVoucher"; script: string }
  "overview.get": { instance: string }
  "scheduler.start": { instance: string }
  "scheduler.stop": { instance: string }
  "tasks.run": { instance: string; task: string }
  "logs.get": { instance: string; after?: number }
  "preview.capture": { instance: string }
  "statistics.refreshLoot": { instance: string }
  "statistics.report": { instance: string; category?: "resources" | "action" | "opsi" | "commission" | "ships" | "loot" | "research"; month?: string | null; days?: number; period?: "day" | "week" | "month"; series?: number; scope?: "series" | "consumable" }
  "meowfficer.scoreReport": { instance: string; limit?: number }
  "meowfficer.clearReport": { instance: string }
  "statistics.resources": { instance: string; days?: number; resource?: "Oil" | "Coin" | "Gem" | "Cube" | "Pt" | "ActionPoint" | "Core" | "Medal" | "Merit" | "GuildCoin" | "YellowCoin" | "PurpleCoin" }
  "settings.get": Record<string, never>
  "settings.patch": { values: Record<string, unknown> }
  "startup.get": { instance: string }
  "startup.set": { instance: string; enabled?: boolean | null; remember?: boolean | null }
  "updater.status": Record<string, never>
  "updater.commits": { offset?: number; limit?: number }
  "updater.fetch": Record<string, never>
  "updater.apply": Record<string, never>
  "updater.cancel": Record<string, never>
  "announcement.get": { force?: boolean }
  "auth.login": { password?: string }
  "events.subscribe": { instance?: string | null; topics: Array<"instances" | "overview" | "logs" | "preview"> }
}
