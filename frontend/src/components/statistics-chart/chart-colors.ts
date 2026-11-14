/**
 * 从 StatisticsChart.tsx 原 51-61 行提取，纯搬迁未改动。
 * 图表系列配色：资源专属色板与默认色板轮转。
 */
const RESOURCE_PALETTE: Record<string, string> = {
  oil: '#10b981', coin: '#f59e0b', cube: '#0ea5e9', gem: '#f43f5e', pt: '#8b5cf6',
  core: '#06b6d4', medal: '#e11d48', merit: '#d97706', guild_coin: '#64748b',
  ap: '#3b82f6', asset: '#84cc16', distance: '#2563eb', yellow_coins: '#eab308', purple_coins: '#a855f7',
}
const DEFAULT_PALETTE = ['#159b88', '#f59e0b', '#0ea5e9', '#ec4899', '#8b5cf6', '#10b981', '#f97316', '#6366f1', '#14b8a6']

/** 系列取色：资源键有专属色，首条系列可用调用方给的回落色，其余按默认色板轮转。 */
export function getSeriesColor(key: string, index: number, fallback?: string): string {
  return RESOURCE_PALETTE[key] ?? (index === 0 && fallback ? fallback : DEFAULT_PALETTE[index % DEFAULT_PALETTE.length])
}
